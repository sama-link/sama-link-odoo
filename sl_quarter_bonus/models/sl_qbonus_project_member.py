from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class SlQbonusProjectMember(models.Model):
    """One row per employee on a project: the points the owner gives them and
    the amount those points are worth once the bonus quarter has a rate."""
    _name = 'sl.qbonus.project.member'
    _description = 'Quarterly Bonus Project Member'
    _order = 'role, id'
    _rec_name = 'employee_id'

    project_id = fields.Many2one(
        'sl.qbonus.project', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    project_state = fields.Selection(related='project_id.state', store=True)
    bonus_quarter_id = fields.Many2one(
        related='project_id.bonus_quarter_id', store=True, string='Bonus Quarter')
    owner_user_id = fields.Many2one(related='project_id.owner_user_id', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    role = fields.Selection(
        [('owner', 'Owner'), ('member', 'Member')], default='member', required=True)
    ratio_pct = fields.Float(string='Ratio %', digits=(5, 2))
    points = fields.Float(digits=(16, 2))
    amount = fields.Monetary(
        compute='_compute_amount', store=True, currency_field='currency_id')
    duration_months = fields.Float(related='project_id.duration_months', store=True)
    basic_salary = fields.Monetary(
        compute='_compute_basic_salary', store=True, currency_field='currency_id')
    monthly_equivalent = fields.Monetary(
        string='Monthly Method', compute='_compute_comparison', store=True,
        currency_field='currency_id',
        help='What the monthly method would have paid for this project: '
             'baseline % x basic salary x project months.')
    diff = fields.Monetary(
        string='Difference', compute='_compute_comparison', store=True,
        currency_field='currency_id')
    beats_monthly = fields.Boolean(
        string='Beats Monthly', compute='_compute_comparison', store=True)
    trend = fields.Char(compute='_compute_trend')

    _sql_constraints = [
        ('project_employee_uniq', 'unique(project_id, employee_id)',
         'An employee can only appear once in a project team.'),
    ]

    @api.depends('points', 'project_id.bonus_quarter_id.rate_per_point')
    def _compute_amount(self):
        for line in self:
            rate = line.project_id.sudo().bonus_quarter_id.rate_per_point or 0.0
            line.amount = line.points * rate

    @api.depends('employee_id', 'project_id.date_received', 'project_id.date_end')
    def _compute_basic_salary(self):
        for line in self:
            project = line.project_id.sudo()
            on_date = project.date_received or project.date_end
            line.basic_salary = line.employee_id._qbonus_basic_salary(on_date) if line.employee_id else 0.0

    @api.depends('basic_salary', 'amount', 'project_id.duration_months',
                 'project_id.bonus_quarter_id.baseline_pct', 'project_id.quarter_id.baseline_pct')
    def _compute_comparison(self):
        for line in self:
            project = line.project_id.sudo()
            quarter = project.bonus_quarter_id or project.quarter_id
            pct = quarter.baseline_pct if quarter else 0.0
            line.monthly_equivalent = line.basic_salary * pct / 100.0 * project.duration_months
            line.diff = line.amount - line.monthly_equivalent
            line.beats_monthly = float_compare(line.diff, 0.0, precision_digits=2) >= 0

    def _compute_trend(self):
        for line in self:
            line.trend = '▲' if line.beats_monthly else '▼'

    @api.constrains('ratio_pct', 'points')
    def _check_values(self):
        for line in self:
            if line.points < 0:
                raise ValidationError(_('Points cannot be negative.'))
            if not 0 <= line.ratio_pct <= 100:
                raise ValidationError(_('Ratio % must be between 0 and 100.'))
        self.mapped('project_id')._check_points_total()

    @api.constrains('employee_id', 'project_id')
    def _check_company(self):
        for line in self:
            if line.employee_id.company_id and line.employee_id.company_id != line.project_id.company_id:
                raise ValidationError(_('%s belongs to another company than the project.')
                                      % line.employee_id.name)

    def _check_open(self):
        for line in self:
            if line.project_id.sudo().bonus_quarter_id.state == 'closed' and not self.env.su:
                raise UserError(_('Quarter %s is closed: project points are locked.')
                                % line.project_id.bonus_quarter_id.name)

    def write(self, vals):
        self._check_open()
        return super().write(vals)

    def unlink(self):
        self._check_open()
        for line in self:
            if line.role == 'owner' and line.project_id.state not in ('draft', 'cancelled') and not self.env.su:
                raise UserError(_('The owner line cannot be removed. Change the project owner instead.'))
        return super().unlink()
