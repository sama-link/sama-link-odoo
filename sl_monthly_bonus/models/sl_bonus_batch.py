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
    employee_ids = fields.Many2many(
        'hr.employee', 'sl_bonus_batch_employee_rel', 'batch_id', 'employee_id',
        string='Employees',
        help='Optional. If set, Compute generates lines ONLY for these employees '
             '(like appraisal batches). Leave empty to compute for all active '
             'employees in the company.',
    )
    line_count = fields.Integer(compute='_compute_counts', store=True)
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

    def action_view_lines(self):
        """Smart-button: open this batch's bonus lines (replaces the global menu)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bonus Lines'),
            'res_model': 'sl.bonus.batch.line',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def action_add_all_employees(self):
        """Convenience: load all active company employees into the selection."""
        self._ensure_hr()
        for rec in self:
            emps = self.env['hr.employee'].sudo().search([
                ('company_id', 'in', [rec.company_id.id, False]),
                ('active', '=', True),
            ])
            rec.employee_ids = [(6, 0, emps.ids)]
        return True

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
            rec.write({
                'state': 'draft',
                'approved_by': False, 'approved_on': False,
                'locked_by': False, 'locked_on': False,
            })

    # ── Compute engine ────────────────────────────────────────────────
    def _compute_lines(self):
        """Refresh batch lines for all active employees in the company.

        Safe to run repeatedly. Manual overrides (line.manual_override_amount with
        manual_override_reason) are preserved across recomputes; only the input
        snapshot and the calculation breakdown components are refreshed for those
        lines. Lines whose employee is no longer active are removed.

        Runs internal writes/unlinks via sudo() so that HR users (who can trigger
        compute via action_compute) don't hit access errors on the internal
        bookkeeping. Outer permission gating already happened in action_compute.
        """
        self.ensure_one()
        Calc = self.env['sl.bonus.calculator'].sudo()
        Line = self.env['sl.bonus.batch.line'].sudo()
        Component = self.env['sl.bonus.batch.line.component'].sudo()
        if self.employee_ids:
            # Selected-employees mode (like appraisal batches): only these.
            employees = self.employee_ids.sudo().filtered(lambda e: e.active)
        else:
            # Default: all active employees in the company.
            employees = self.env['hr.employee'].sudo().search([
                ('company_id', 'in', [self.company_id.id, False]),
                ('active', '=', True),
            ])
        if not employees:
            raise UserError(_(
                "No employees to compute. Add employees to the batch, or — if you "
                "left the selection empty — ensure active employees exist for '%s'."
            ) % self.company_id.name)
        existing_lines = {l.employee_id.id: l for l in self.sudo().line_ids}
        seen_emp_ids = set()
        for emp in employees:
            seen_emp_ids.add(emp.id)
            result = Calc.calculate_for_employee(emp, self.period_start, self.period_end)
            line_vals = result['line_vals']
            line_vals['batch_id'] = self.id
            line_vals['employee_id'] = emp.id
            if emp.id in existing_lines:
                line = existing_lines[emp.id].sudo()
                # Preserve manual override on the bonus_amount column.
                has_override = bool(line.manual_override_reason) and line.manual_override_amount is not False
                if has_override:
                    overridden_amount = line.manual_override_amount
                    line.write({**line_vals, 'bonus_amount': overridden_amount})
                else:
                    line.write(line_vals)
                # Replace components atomically via sudo (HR otherwise may lack unlink).
                if line.component_ids:
                    line.component_ids.sudo().unlink()
            else:
                line = Line.create(line_vals)
            if result.get('components'):
                Component.create([
                    dict(c, line_id=line.id) for c in result['components']
                ])
        # Remove lines for employees no longer present (e.g. archived since last run).
        to_remove = self.sudo().line_ids.filtered(lambda l: l.employee_id.id not in seen_emp_ids)
        if to_remove:
            to_remove.sudo().unlink()

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
