from datetime import date
from calendar import monthrange
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError


class SlBonusSelfEstimate(models.Model):
    """Employee self-service: enter an expected evaluation % and see the estimated bonus.

    One record per (employee, period_start). Employees can only see/write their own row.
    """
    _name = 'sl.bonus.self.estimate'
    _description = 'Self-Service Bonus Estimate'
    _order = 'period_start desc, employee_id'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        default=lambda self: self.env.user.employee_id, ondelete='cascade',
    )
    user_id = fields.Many2one(
        related='employee_id.user_id', store=True, readonly=True,
    )
    period_start = fields.Date(
        string='Month', required=True,
        default=lambda self: date.today().replace(day=1),
    )
    period_end = fields.Date(
        string='Period End', compute='_compute_period_end', store=True,
    )
    period_label = fields.Char(
        string='Month', compute='_compute_period_label', store=True,
        help='Month/Year of this estimate (no day).',
    )
    expected_evaluation_percent = fields.Float(
        string='Expected Evaluation %', default=85.0,
        help='Your expected total evaluation score (0–100). Used only to estimate this page.',
    )
    estimated_amount = fields.Monetary(
        string='Estimated Bonus',
        compute='_compute_estimate', store=False,
        currency_field='currency_id',
    )
    category = fields.Selection([
        ('service', 'Service'),
        ('sales', 'Sales'),
        ('sales_online', 'Sales Online'),
        ('sales_projects', 'Sales Projects'),
        ('stock', 'Stock Purchasing'),
        ('installation', 'Installation'),
        ('branch_manager', 'Branch / Area Manager'),
        ('none', 'No Monthly Bonus'),
    ], compute='_compute_estimate', string='Category')
    breakdown_html = fields.Html(
        string='Breakdown', compute='_compute_estimate', sanitize=False,
    )
    is_excluded = fields.Boolean(compute='_compute_estimate')
    exclusion_reason = fields.Char(compute='_compute_estimate')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True, readonly=True,
    )
    progress_target = fields.Monetary(compute='_compute_estimate', currency_field='currency_id')
    progress_achieved = fields.Monetary(compute='_compute_estimate', currency_field='currency_id')
    progress_pct = fields.Float(compute='_compute_estimate')

    _sql_constraints = [
        ('uniq_emp_period',
         'unique(employee_id, period_start)',
         'You already have an estimate for this month — open the existing one.'),
    ]

    @api.depends('employee_id', 'period_start')
    def _compute_name(self):
        for rec in self:
            period = rec.period_start and rec.period_start.strftime('%Y-%m') or ''
            rec.name = f"{rec.employee_id.name or ''} — {period}"

    @api.depends('period_start')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = rec.period_start.strftime('%m/%Y') if rec.period_start else ''

    @api.depends('period_start')
    def _compute_period_end(self):
        for rec in self:
            if rec.period_start:
                y, m = rec.period_start.year, rec.period_start.month
                rec.period_end = date(y, m, monthrange(y, m)[1])
            else:
                rec.period_end = False

    @api.depends('employee_id', 'period_start', 'period_end', 'expected_evaluation_percent')
    def _compute_estimate(self):
        Calc = self.env['sl.bonus.calculator'].sudo()
        for rec in self:
            if not rec.employee_id or not rec.period_start or not rec.period_end:
                rec.estimated_amount = 0.0
                rec.category = 'none'
                rec.breakdown_html = ''
                rec.is_excluded = False
                rec.exclusion_reason = ''
                rec.progress_target = 0.0
                rec.progress_achieved = 0.0
                rec.progress_pct = 0.0
                continue
            # Calculate using the engine, but override evaluation% with the expected one.
            # We monkey-patch via context: the engine reads via _get_evaluation_percent.
            # Simpler: call private internals through a thin wrapper.
            result = rec._estimate_with_expected_eval(Calc)
            line_vals = result['line_vals']
            rec.estimated_amount = line_vals.get('computed_amount') or 0.0
            rec.category = line_vals.get('category') or 'none'
            rec.is_excluded = bool(line_vals.get('is_excluded'))
            rec.exclusion_reason = line_vals.get('exclusion_reason') or ''
            rec.progress_target = line_vals.get('target_amount') or 0.0
            rec.progress_achieved = line_vals.get('achieved_amount') or 0.0
            rec.progress_pct = line_vals.get('achievement_percent') or 0.0
            parts = ['<table class="table table-sm" style="direction:rtl;text-align:right;">']
            for c in result.get('components', []):
                # Internal commission-split detail is shown only in the HR
                # Monthly Bonus breakdown, not in the employee's My Bonus estimate.
                if c.get('self_hidden'):
                    continue
                parts.append(
                    f"<tr><td style='font-weight:600'>{c.get('label','')}</td>"
                    f"<td>{c.get('value','')}</td></tr>"
                )
            parts.append('</table>')
            rec.breakdown_html = ''.join(parts)

    def _estimate_with_expected_eval(self, Calc):
        """Run the engine but force the expected evaluation%."""
        self.ensure_one()
        # Replicate engine logic with our expected_evaluation_percent.
        result = Calc._init_result(self.employee_id, self.period_start, self.period_end)
        excluded, reason = Calc._compute_exclusion(self.employee_id, self.period_end)
        if excluded:
            result['line_vals'].update({
                'category': self.employee_id.job_id.bonus_category or 'none',
                'is_excluded': True,
                'exclusion_reason': reason,
                'computed_amount': 0.0, 'bonus_amount': 0.0,
            })
            result['components'].append({
                'sequence': 10, 'label': _('Excluded'),
                'value': reason or _('Excluded'),
            })
            return result
        category = Calc._resolve_category(self.employee_id)
        result['line_vals']['category'] = category
        eval_pct = float(self.expected_evaluation_percent or 0.0)
        result['line_vals']['evaluation_percent'] = eval_pct
        result['line_vals']['evaluation_source'] = _('Expected (entered by employee)')
        method = getattr(Calc, f'_calc_{category}', None)
        if not method:
            result['line_vals'].update({
                'is_excluded': True,
                'exclusion_reason': _('No formula configured for category %s.') % category,
                'computed_amount': 0.0,
            })
            return result
        method(self.employee_id, self.period_start, self.period_end, eval_pct, result)
        return result

    @api.model
    def open_or_create_current(self):
        """Open the current-month estimate for the logged-in user (create if missing)."""
        emp = self.env.user.employee_id
        if not emp:
            raise UserError(_("Your user is not linked to an employee."))
        today = fields.Date.today()
        period_start = today.replace(day=1)
        rec = self.sudo().search([
            ('employee_id', '=', emp.id), ('period_start', '=', period_start),
        ], limit=1)
        if not rec:
            rec = self.sudo().create({
                'employee_id': emp.id,
                'period_start': period_start,
            })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        # SUPERUSER (sudo / cron / migrations) bypasses ownership check —
        # without this, batch back-ends and tests that create estimates on
        # behalf of users via sudo() would fail.
        is_superuser = self.env.su or self.env.user.id == 1
        for v in vals_list:
            v.setdefault('employee_id', self.env.user.employee_id.id)
            if is_superuser:
                continue
            # Enforce ownership: a non-admin user can only create rows for themselves.
            if not self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
                    and not self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager'):
                if v.get('employee_id') != (self.env.user.employee_id.id or False):
                    raise AccessError(_("You can only create your own estimate."))
        return super().create(vals_list)

    @api.model
    def cron_cleanup_old_estimates(self):
        """Delete self-estimate records older than 2 months.

        The "current month estimate" form auto-creates a new row each month;
        we don't want unbounded history. Kept simple: anything whose
        ``period_start`` is more than 2 calendar months before today is
        removed. Idempotent — safe to run repeatedly.
        """
        today = fields.Date.today()
        # Cutoff = first day of (today - 2 months). Any row strictly older is removed.
        year, month = today.year, today.month - 2
        while month <= 0:
            month += 12
            year -= 1
        cutoff = date(year, month, 1)
        old = self.sudo().search([('period_start', '<', cutoff)])
        n = len(old)
        if old:
            old.unlink()
        return n
