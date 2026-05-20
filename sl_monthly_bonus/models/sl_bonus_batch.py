import logging
from datetime import date
from calendar import monthrange
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError

_logger = logging.getLogger(__name__)


class SlBonusBatch(models.Model):
    """Monthly bonus batch (header). One batch per (company, month)."""
    _name = 'sl.bonus.batch'
    _description = 'Monthly Bonus Batch'
    _order = 'period_start desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    period_start = fields.Date(string='Period Start', required=True)
    period_end = fields.Date(string='Period End', required=True)
    period_label = fields.Char(string='Month', compute='_compute_period_label', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('data_ready', 'Data Ready'),
        ('computed', 'Computed'),
        ('hr_review', 'HR Review'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], default='draft', tracking=True, copy=False, string='State')
    line_ids = fields.One2many(
        'sl.bonus.batch.line', 'batch_id',
        string='Bonus Lines', copy=False,
    )
    line_count = fields.Integer(compute='_compute_counts', store=True)
    paid_count = fields.Integer(
        string='Eligible / Paid Count', compute='_compute_counts', store=True,
        help='Number of lines that will be paid (non-excluded, non-zero).',
    )
    computed_count = fields.Integer(
        string='Computed Count', compute='_compute_counts', store=True,
        help='Number of lines whose engine result is non-zero, including overrides.',
    )
    total_amount = fields.Monetary(
        string='Total', compute='_compute_counts', store=True,
        currency_field='currency_id',
    )
    excluded_count = fields.Integer(compute='_compute_counts', store=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    treat_missing_eval_as_full = fields.Boolean(
        string='Treat Missing Evaluation as 100%',
        default=False, tracking=True, copy=False,
        help='If enabled, employees without a finalized monthly evaluation receive a '
             '100% evaluation for this batch instead of 0%. This is an exceptional, '
             'audited setting — every line affected by it is marked and the reason '
             'is shown on the line breakdown and the printed receipt.',
    )
    appraisal_batch_id = fields.Many2one(
        'hr.appraisal.batch', string='Linked Appraisal Batch',
        ondelete='set null', tracking=True,
        help='Appraisal batch for the same period that fed evaluations into this run. '
             'Created automatically when the bonus batch is opened from an appraisal batch.',
    )
    created_by = fields.Many2one(
        'res.users', readonly=True, default=lambda self: self.env.user,
    )
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_on = fields.Datetime(readonly=True)
    locked_by = fields.Many2one('res.users', readonly=True)
    locked_on = fields.Datetime(readonly=True)
    last_computed_on = fields.Datetime(readonly=True)
    last_computed_by = fields.Many2one('res.users', readonly=True)
    note = fields.Text(string='Note')

    _sql_constraints = [
        ('uniq_company_period',
         'unique(company_id, period_start, period_end)',
         'A bonus batch for this company and period already exists.'),
    ]

    @api.depends('period_start')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = rec.period_start and rec.period_start.strftime('%Y-%m') or ''

    @api.depends('line_ids', 'line_ids.bonus_amount', 'line_ids.is_excluded')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.total_amount = sum(l.bonus_amount for l in rec.line_ids if not l.is_excluded)
            rec.excluded_count = sum(1 for l in rec.line_ids if l.is_excluded)
            rec.paid_count = sum(
                1 for l in rec.line_ids
                if not l.is_excluded and (l.bonus_amount or 0.0) > 0
            )
            rec.computed_count = sum(
                1 for l in rec.line_ids
                if (l.computed_amount or 0.0) > 0 or (l.bonus_amount or 0.0) > 0
            )

    @api.constrains('period_start', 'period_end')
    def _check_period(self):
        for rec in self:
            if rec.period_end < rec.period_start:
                raise ValidationError(_("Period End must be after Period Start."))

    # ── Permission helpers ────────────────────────────────────────────
    def _is_admin(self):
        return self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
            or self.env.user.has_group('base.group_system')

    def _is_hr(self):
        return self._is_admin() \
            or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')

    def _ensure_hr(self):
        if not self._is_hr():
            raise AccessError(_("Only HR Manager / Admin can perform this action."))

    # ── Workflow actions ──────────────────────────────────────────────
    def action_open_for_previous_month(self):
        """Helper button: create / open the batch covering the previous calendar month."""
        self._ensure_hr()
        today = fields.Date.today()
        year = today.year
        month = today.month - 1
        if month == 0:
            month = 12
            year -= 1
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        existing = self.search([
            ('company_id', '=', self.env.company.id),
            ('period_start', '=', start),
            ('period_end', '=', end),
        ], limit=1)
        if existing:
            return existing._return_form_action()
        batch = self.create({
            'name': _('Bonus %s') % start.strftime('%Y-%m'),
            'period_start': start,
            'period_end': end,
        })
        return batch._return_form_action()

    def _return_form_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_data_ready(self):
        self._ensure_hr()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only Draft batches can be moved to Data Ready."))
            rec.state = 'data_ready'

    def action_compute(self):
        self._ensure_hr()
        for rec in self:
            if rec.state not in ('data_ready', 'computed', 'hr_review'):
                raise UserError(_("Compute is allowed only in Data Ready / Computed / HR Review states."))
            rec._compute_lines()
            rec.write({
                'state': 'computed',
                'last_computed_on': fields.Datetime.now(),
                'last_computed_by': self.env.user.id,
            })
            rec.message_post(body=_("Bonuses recomputed by %s.") % self.env.user.name)

    def action_send_to_review(self):
        self._ensure_hr()
        for rec in self:
            if rec.state != 'computed':
                raise UserError(_("Only Computed batches can be sent to HR Review."))
            rec.state = 'hr_review'

    def action_approve(self):
        self._ensure_hr()
        for rec in self:
            if rec.state != 'hr_review':
                raise UserError(_("Only HR Review batches can be Approved."))
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
            rec.message_post(body=_("Batch approved."))

    def action_lock(self):
        if not self._is_admin():
            raise AccessError(_("Only Admin can lock an approved batch."))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only Approved batches can be Locked."))
            rec.write({
                'state': 'locked',
                'locked_by': self.env.user.id,
                'locked_on': fields.Datetime.now(),
            })

    def action_reset_to_draft(self):
        if not self._is_admin():
            raise AccessError(_("Only Admin can reset a batch to draft."))
        for rec in self:
            old_state = rec.state
            rec.write({
                'state': 'draft',
                'approved_by': False, 'approved_on': False,
                'locked_by': False, 'locked_on': False,
            })
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=self._name, res_id=rec.id,
                action='reset_to_draft',
                old_value=old_state, new_value='draft',
                reason='Admin reset to draft',
                batch_id=rec.id,
            )

    def action_open_manual_state_change(self):
        """Open the Admin-only manual state change wizard for stuck batches."""
        self.ensure_one()
        if not self._is_admin():
            raise AccessError(_("Only Admin can manually change a batch state."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sl.bonus.state.change.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id},
        }

    def action_export_payout_xlsx(self):
        """Header button — download the Bonus Payout XLSX for this batch."""
        self.ensure_one()
        if self.state not in ('hr_review', 'approved', 'locked'):
            raise UserError(_(
                "Payout sheet is only available once the batch reaches HR Review or later."
            ))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/sl_monthly_bonus/batch/{self.id}/payout.xlsx',
            'target': 'self',
        }

    def action_print_payout_pdf(self):
        """Header button — print the QWeb payout PDF."""
        self.ensure_one()
        if self.state not in ('hr_review', 'approved', 'locked'):
            raise UserError(_(
                "Payout PDF is only available once the batch reaches HR Review or later."
            ))
        return self.env.ref('sl_monthly_bonus.action_report_bonus_payout').report_action(self)

    def action_print_department_pdf(self):
        self.ensure_one()
        return self.env.ref('sl_monthly_bonus.action_report_bonus_department').report_action(self)

    def _department_performance_rows(self):
        """Used by the Department Performance QWeb report. Returns a list of dicts:
        [{'department', 'count', 'eligible', 'excluded', 'avg_eval', 'total'}]
        sorted by department name.
        """
        self.ensure_one()
        bucket = {}
        for l in self.line_ids:
            key = l.department_id.id or 0
            agg = bucket.setdefault(key, {
                'department': l.department_id.name or _('No Department'),
                'count': 0, 'eligible': 0, 'excluded': 0,
                'sum_eval': 0.0, 'total': 0.0,
            })
            agg['count'] += 1
            agg['sum_eval'] += l.evaluation_percent or 0.0
            if l.is_excluded:
                agg['excluded'] += 1
            else:
                agg['eligible'] += 1
                agg['total'] += l.bonus_amount or 0.0
        rows = []
        for agg in bucket.values():
            rows.append({
                'department': agg['department'],
                'count': agg['count'],
                'eligible': agg['eligible'],
                'excluded': agg['excluded'],
                'avg_eval': round((agg['sum_eval'] / agg['count']) if agg['count'] else 0.0, 2),
                'total': round(agg['total'], 2),
            })
        return sorted(rows, key=lambda r: r['department'])

    def action_open_compute_wizard(self):
        """Open the per-employee / per-group compute wizard."""
        self.ensure_one()
        self._ensure_hr()
        if self.state not in ('data_ready', 'computed', 'hr_review'):
            raise UserError(_(
                "Per-employee compute is only allowed when the batch is in "
                "Data Ready / Computed / HR Review (not in '%s')."
            ) % self.state)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sl.bonus.compute.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_batch_id': self.id},
        }

    def action_compute_employees(self, employee_ids):
        """Compute (or recompute) bonus lines for a specific set of employees only.

        Safe to call repeatedly. Manual overrides on those lines are preserved.
        Other lines on the batch are left untouched.
        Returns the affected sl.bonus.batch.line recordset.
        """
        self.ensure_one()
        self._ensure_hr()
        if self.state not in ('data_ready', 'computed', 'hr_review'):
            raise UserError(_(
                "Cannot compute employees: batch is in '%s' state. "
                "Allowed states: Data Ready / Computed / HR Review."
            ) % self.state)
        Employee = self.env['hr.employee'].sudo()
        employees = Employee.browse(employee_ids).exists()
        if not employees:
            raise UserError(_("Please select at least one employee to compute."))
        affected = self._compute_subset(employees)
        # Stay in Computed (or stay in HR Review — re-entry is intentional).
        target_state = 'computed' if self.state in ('data_ready', 'computed') else self.state
        self.write({
            'state': target_state,
            'last_computed_on': fields.Datetime.now(),
            'last_computed_by': self.env.user.id,
        })
        self.message_post(body=_(
            "Recomputed %(n)s employee(s) by %(user)s."
        ) % {'n': len(employees), 'user': self.env.user.name})
        return affected

    # ── Compute engine ────────────────────────────────────────────────
    def _compute_lines(self):
        """Refresh batch lines for ALL active employees in the company.

        Safe to run repeatedly. Manual overrides are preserved. Lines whose
        employee is no longer active are removed. The compute pass propagates
        treat_missing_eval_as_full via context so the calculator can honor it.
        """
        self.ensure_one()
        employees = self.env['hr.employee'].sudo().search([
            ('company_id', 'in', [self.company_id.id, False]),
            ('active', '=', True),
        ])
        if not employees:
            raise UserError(_(
                "No active employees found for company '%s'. "
                "Make sure at least one employee exists before computing bonuses."
            ) % self.company_id.name)
        self._refresh_lines_for(employees, prune_others=True)

    def _compute_subset(self, employees):
        """Refresh lines for a subset of employees. Untouched lines stay as-is."""
        self.ensure_one()
        return self._refresh_lines_for(employees, prune_others=False)

    def _refresh_lines_for(self, employees, prune_others):
        """Shared refresh logic used by both full and subset compute paths."""
        self.ensure_one()
        Calc = self.env['sl.bonus.calculator'].sudo().with_context(
            sl_bonus_treat_missing_eval_as_full=self.treat_missing_eval_as_full,
        )
        Line = self.env['sl.bonus.batch.line'].sudo()
        Component = self.env['sl.bonus.batch.line.component'].sudo()
        existing_lines = {l.employee_id.id: l for l in self.sudo().line_ids}
        seen_emp_ids = set()
        affected = self.env['sl.bonus.batch.line'].sudo()
        for emp in employees:
            seen_emp_ids.add(emp.id)
            result = Calc.calculate_for_employee(emp, self.period_start, self.period_end)
            line_vals = result['line_vals']
            line_vals['batch_id'] = self.id
            line_vals['employee_id'] = emp.id
            if emp.id in existing_lines:
                line = existing_lines[emp.id].sudo()
                has_override = bool(line.manual_override_reason) and line.manual_override_amount is not False
                if has_override:
                    line.write({**line_vals, 'bonus_amount': line.manual_override_amount})
                else:
                    line.write(line_vals)
                if line.component_ids:
                    line.component_ids.sudo().unlink()
            else:
                line = Line.create(line_vals)
            if result.get('components'):
                Component.create([
                    dict(c, line_id=line.id) for c in result['components']
                ])
            affected |= line
        if prune_others:
            to_remove = self.sudo().line_ids.filtered(lambda l: l.employee_id.id not in seen_emp_ids)
            if to_remove:
                to_remove.sudo().unlink()
        return affected

    def unlink(self):
        """Deletion policy:
          - draft / data_ready : HR Manager or Admin may delete.
          - computed / hr_review: only Admin may delete (preserves audit-able runs).
          - approved / locked  : nobody may delete via standard unlink.
        Lines and components cascade via Odoo's ondelete='cascade'.
        """
        is_admin = self._is_admin()
        is_hr = self._is_hr()
        for rec in self:
            if rec.state in ('approved', 'locked'):
                raise UserError(_(
                    "Batch '%(name)s' is %(state)s and cannot be deleted. "
                    "Reset it to draft first (Admin only)."
                ) % {'name': rec.name, 'state': rec.state})
            if rec.state in ('computed', 'hr_review') and not is_admin:
                raise UserError(_(
                    "Batch '%(name)s' is in '%(state)s' state. Only an Admin can delete it; "
                    "otherwise reset it to draft first."
                ) % {'name': rec.name, 'state': rec.state})
            if not (is_hr or is_admin):
                raise AccessError(_(
                    "You don't have permission to delete bonus batches. Contact HR / Admin."
                ))
        return super().unlink()
