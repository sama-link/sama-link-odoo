import calendar
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

QUARTER_SELECTION = [('1', 'Q1'), ('2', 'Q2'), ('3', 'Q3'), ('4', 'Q4')]


class SlQbonusQuarter(models.Model):
    """One bonus pool per company per quarter.

    The pool is the only number management decides; the EGP-per-point rate is
    derived from it and from the points of every project *received* in the
    quarter. Closing the quarter freezes projects, member points and the
    employee bonus lines built by ``action_compute``.
    """
    _name = 'sl.qbonus.quarter'
    _description = 'Quarterly Project Bonus - Quarter'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'year desc, quarter desc, company_id'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    year = fields.Integer(
        required=True, default=lambda self: fields.Date.context_today(self).year)
    quarter = fields.Selection(
        QUARTER_SELECTION, required=True,
        default=lambda self: str(self._quarter_number(fields.Date.context_today(self))))
    date_start = fields.Date(compute='_compute_dates', store=True)
    date_end = fields.Date(compute='_compute_dates', store=True)
    state = fields.Selection(
        [('open', 'Open'), ('closed', 'Closed')],
        default='open', required=True, tracking=True, copy=False)
    pool_amount = fields.Monetary(
        string='Bonus Pool', currency_field='currency_id', tracking=True,
        help='Total amount management allocates to this quarter for this '
             'company. Rate per point = pool / points of all projects '
             'received in the quarter.')
    baseline_pct = fields.Float(
        string='Monthly Baseline %', digits=(5, 2),
        default=lambda self: self._default_baseline_pct(),
        help='Comparison only: monthly-method equivalent = baseline % x basic '
             'salary x project months. Defaults from Settings.')
    total_points = fields.Float(
        string='Points Received', compute='_compute_totals', store=True, digits=(16, 2))
    rate_per_point = fields.Monetary(
        string='Rate per Point', compute='_compute_totals', store=True,
        currency_field='currency_id')
    distributed_points = fields.Float(
        compute='_compute_totals', store=True, digits=(16, 2))
    undistributed_points = fields.Float(
        compute='_compute_totals', store=True, digits=(16, 2))
    total_amount = fields.Monetary(
        string='Distributed Amount', compute='_compute_totals', store=True,
        currency_field='currency_id')
    project_ids = fields.One2many(
        'sl.qbonus.project', 'bonus_quarter_id', string='Projects Received')
    target_project_ids = fields.One2many(
        'sl.qbonus.project', 'quarter_id', string='Projects Targeted')
    line_ids = fields.One2many(
        'sl.qbonus.line', 'quarter_id', string='Employee Bonus Lines')
    project_count = fields.Integer(compute='_compute_counts')
    late_project_count = fields.Integer(compute='_compute_counts')
    line_count = fields.Integer(compute='_compute_counts')
    beat_count = fields.Integer(
        string='Employees Beating Monthly', compute='_compute_counts')
    note = fields.Text()

    _sql_constraints = [
        ('company_year_quarter_uniq', 'unique(company_id, year, quarter)',
         'A quarter record already exists for this company, year and quarter.'),
    ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _quarter_number(d):
        return (d.month - 1) // 3 + 1

    @api.model
    def _default_baseline_pct(self):
        return float(self.env['ir.config_parameter'].sudo().get_param(
            'sl_quarter_bonus.baseline_pct', 25.0) or 0.0)

    @api.model
    def _get_or_create(self, company, on_date):
        """Return the quarter record covering ``on_date`` for ``company``,
        creating it (as superuser) when it does not exist yet."""
        year, qn = on_date.year, str(self._quarter_number(on_date))
        Quarter = self.sudo()
        quarter = Quarter.search([
            ('company_id', '=', company.id),
            ('year', '=', year),
            ('quarter', '=', qn),
        ], limit=1)
        if not quarter:
            quarter = Quarter.create({
                'company_id': company.id,
                'year': year,
                'quarter': qn,
            })
        return quarter

    def _check_admin(self):
        if not self.env.su and not self.env.user.has_group('sl_quarter_bonus.group_qbonus_admin'):
            raise AccessError(_('Only a Project Admin can do this.'))

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('company_id.name', 'year', 'quarter')
    def _compute_name(self):
        for q in self:
            q.name = 'Q%s %s - %s' % (q.quarter or '?', q.year or '?', q.company_id.name or '')

    @api.depends('year', 'quarter')
    def _compute_dates(self):
        for q in self:
            if q.year and q.quarter:
                first_month = (int(q.quarter) - 1) * 3 + 1
                last_month = first_month + 2
                q.date_start = date(q.year, first_month, 1)
                q.date_end = date(q.year, last_month, calendar.monthrange(q.year, last_month)[1])
            else:
                q.date_start = q.date_end = False

    @api.depends('pool_amount', 'project_ids.points_earned', 'project_ids.state',
                 'project_ids.member_line_ids.points')
    def _compute_totals(self):
        for q in self:
            received = q.project_ids.filtered(lambda p: p.state == 'received')
            total = sum(received.mapped('points_earned'))
            distributed = sum(received.mapped('member_line_ids').mapped('points'))
            q.total_points = total
            q.rate_per_point = (q.pool_amount / total) if total > 0 else 0.0
            q.distributed_points = distributed
            q.undistributed_points = total - distributed
            q.total_amount = distributed * q.rate_per_point

    def _compute_counts(self):
        for q in self:
            q.project_count = len(q.project_ids.filtered(lambda p: p.state == 'received'))
            q.late_project_count = len((q.target_project_ids | q.project_ids).filtered('is_late'))
            q.line_count = len(q.line_ids)
            q.beat_count = len(q.line_ids.filtered('beats_monthly'))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_compute(self):
        """(Re)build the per-employee bonus lines from the member points of
        every project received in this quarter."""
        self._check_admin()
        Line = self.env['sl.qbonus.line'].sudo()
        Employee = self.env['hr.employee'].sudo()
        for q in self:
            q.line_ids.sudo().unlink()
            received = q.project_ids.filtered(lambda p: p.state == 'received')
            per_employee = {}
            for ml in received.mapped('member_line_ids'):
                if not ml.employee_id:
                    continue
                data = per_employee.setdefault(ml.employee_id.id, {
                    'points': 0.0, 'amount': 0.0, 'months': 0.0, 'projects': set(),
                })
                data['points'] += ml.points
                data['amount'] += ml.amount
                data['months'] += ml.project_id.duration_months
                data['projects'].add(ml.project_id.id)
            vals_list = []
            for emp_id, data in per_employee.items():
                employee = Employee.browse(emp_id)
                basic = employee._qbonus_basic_salary(q.date_end)
                monthly = basic * q.baseline_pct / 100.0 * data['months']
                calendar_eq = basic * q.baseline_pct / 100.0 * 3.0
                vals_list.append({
                    'quarter_id': q.id,
                    'employee_id': emp_id,
                    'points': data['points'],
                    'amount': data['amount'],
                    'basic_salary': basic,
                    'project_months': data['months'],
                    'monthly_equivalent': monthly,
                    'calendar_equivalent': calendar_eq,
                    'project_ids': [(6, 0, list(data['projects']))],
                })
            if vals_list:
                Line.create(vals_list)
            q.message_post(body=_('Bonus lines computed: %s employee(s), rate %s per point.')
                           % (len(vals_list), q.rate_per_point))
        return True

    def action_close(self):
        self._check_admin()
        for q in self:
            if q.state == 'closed':
                continue
            if q.pool_amount <= 0:
                raise UserError(_('Set the bonus pool before closing %s.') % q.name)
            pending = q.project_ids.filtered(
                lambda p: p.state == 'received' and p.points_undistributed > 0.005)
            if pending:
                raise UserError(_(
                    'These received projects still have undistributed points: %s. '
                    'Ask the owners to distribute them before closing.'
                ) % ', '.join(pending.mapped('name')))
            q.action_compute()
            q.write({'state': 'closed'})
        return True

    def action_reopen(self):
        self._check_admin()
        self.write({'state': 'open'})
        return True

    def action_view_projects(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sl_quarter_bonus.action_sl_qbonus_project')
        action['domain'] = [('bonus_quarter_id', '=', self.id)]
        action['context'] = {'default_quarter_id': self.id, 'default_company_id': self.company_id.id}
        return action

    def action_view_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sl_quarter_bonus.action_sl_qbonus_line')
        action['domain'] = [('quarter_id', '=', self.id)]
        action['context'] = {'search_default_group_employee': 0}
        return action

    def write(self, vals):
        if not self.env.su and 'pool_amount' in vals and any(q.state == 'closed' for q in self):
            raise UserError(_('Reopen the quarter before changing its pool.'))
        return super().write(vals)
