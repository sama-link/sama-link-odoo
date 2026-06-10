from datetime import date
from calendar import monthrange
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError

from .sl_bonus_batch import _format_month_localized


# Mapping from batch state (6 values) → line state (4 values).
# - draft / data_ready  → draft  : nothing computed yet for the line.
# - computed / hr_review → computed : numbers exist, awaiting approval.
# - approved            → approved
# - locked              → locked
_BATCH_TO_LINE_STATE = {
    'draft': 'draft',
    'data_ready': 'draft',
    'computed': 'computed',
    'hr_review': 'computed',
    'approved': 'approved',
    'locked': 'locked',
}


class SlBonusBatchLine(models.Model):
    """One bonus line per employee.

    A line may belong to a ``sl.bonus.batch`` (batch-owned) OR exist
    independently (no batch_id), mirroring how ``hr.payslip`` can live inside
    or outside a payslip run. Independent lines are created and computed
    one-by-one from the standalone Bonuses menu.

    Workflow:
      - draft     → newly created or reset
      - computed  → calculator filled inputs/outputs and breakdown
      - approved  → HR/Admin endorsed the amount
      - locked    → Admin sealed the line; read-only thereafter

    For batch-owned lines, the batch's state transitions write through to all
    child lines. For independent lines, the line's own buttons drive the state.
    """
    _name = 'sl.bonus.batch.line'
    _description = 'Monthly Bonus Batch Line'
    _order = 'period_start desc, batch_id desc, employee_id'
    _inherit = ['mail.thread']

    # ── Batch link (now OPTIONAL — independent lines have NULL batch_id) ──
    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Batch', ondelete='cascade',
        index=True, copy=False,
        help='Parent monthly batch. Leave empty for an independent one-employee bonus.',
    )
    # Legacy field — kept for backward compatibility with existing views,
    # security rules, and any external code that already reads it. Returns
    # False for independent lines (no batch).
    batch_state = fields.Selection(related='batch_id.state', store=True)

    # Period / company / currency — auto-filled from batch when present,
    # otherwise user-set on independent lines. NB: NOT `required=True` on the
    # field itself because Odoo creates computed-stored fields with no value
    # at INSERT time (compute fills them post-insert). Required-ness is
    # enforced via _check_period_required below.
    period_start = fields.Date(
        string='Period Start', index=True,
        compute='_compute_period_fields', store=True, readonly=False,
    )
    period_end = fields.Date(
        string='Period End',
        compute='_compute_period_fields', store=True, readonly=False,
    )
    period_label = fields.Char(
        string='Month (YYYY-MM)', compute='_compute_period_label', store=True,
        help='Technical identifier (YYYY-MM). For display, prefer period_display.',
    )
    # Human-readable month name in the user's UI language. Not stored — the
    # locale comes from request context.
    period_display = fields.Char(string='Month', compute='_compute_period_display')
    company_id = fields.Many2one(
        'res.company', string='Company',
        compute='_compute_company_currency', store=True, readonly=False,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        compute='_compute_company_currency', store=True, readonly=False,
        default=lambda self: self.env.company.currency_id,
    )

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='restrict', index=True,
    )
    user_id = fields.Many2one(
        related='employee_id.user_id', store=True, readonly=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, readonly=True,
    )
    work_location_id = fields.Many2one(
        related='employee_id.work_location_id', store=True, readonly=True,
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', store=True, readonly=True,
    )

    # ── Workflow state ────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='State', default='draft', required=True, copy=False, tracking=True,
        index=True)
    is_independent = fields.Boolean(
        string='Independent', compute='_compute_is_independent', store=True,
        help='True when this line has no parent batch.',
    )

    # ── Calculation inputs / outputs ──────────────────────────────────
    category = fields.Selection([
        ('service', 'Service'),
        ('sales', 'Sales'),
        ('stock', 'Stock Purchasing'),
        ('installation', 'Installation'),
        ('branch_manager', 'Branch / Area Manager'),
        ('none', 'No Monthly Bonus'),
    ], string='Category', readonly=True)
    basic_salary = fields.Monetary(string='Basic Salary', currency_field='currency_id', readonly=True)
    evaluation_percent = fields.Float(string='Evaluation %', readonly=True,
                                      help='Final approved evaluation percentage (0–100).')
    evaluation_source = fields.Char(string='Evaluation Source', readonly=True,
                                    help='Reference to the appraisal record used.')
    target_amount = fields.Monetary(string='Target Amount', currency_field='currency_id', readonly=True)
    achieved_amount = fields.Monetary(string='Achieved Amount', currency_field='currency_id', readonly=True)
    achievement_percent = fields.Float(string='Achievement %', readonly=True)
    tier_name = fields.Char(string='Sales Tier', readonly=True)
    tier_commission = fields.Monetary(string='Tier Commission', currency_field='currency_id', readonly=True)
    stock_sales_value = fields.Monetary(string='Stock Sales Value', currency_field='currency_id', readonly=True)
    stock_commission_pct = fields.Float(string='Stock Commission %', readonly=True)
    installation_fixed_amount = fields.Monetary(string='Installation Fixed', currency_field='currency_id', readonly=True)
    branch_profit_factor = fields.Float(string='Branch Profit Factor', readonly=True)
    branch_manager_pct = fields.Float(string='Branch Manager %', readonly=True)
    service_pct = fields.Float(string='Service %', readonly=True)

    computed_amount = fields.Monetary(
        string='Computed Bonus', currency_field='currency_id', readonly=True,
        help='Engine-calculated bonus before any manual override.',
    )
    bonus_amount = fields.Monetary(
        string='Bonus', currency_field='currency_id',
        tracking=True,
        help='Final amount that will be paid. Equals Computed unless manually adjusted.',
    )
    is_excluded = fields.Boolean(string='Excluded', readonly=True, default=False)
    exclusion_reason = fields.Char(string='Exclusion Reason', readonly=True)
    manual_override_amount = fields.Monetary(
        string='Manual Override Amount', currency_field='currency_id',
        copy=False,
    )
    manual_override_reason = fields.Text(string='Override Reason', copy=False)
    manual_override_by = fields.Many2one('res.users', readonly=True, copy=False)
    manual_override_on = fields.Datetime(readonly=True, copy=False)
    # Approve / lock metadata — only used for INDEPENDENT lines. Batch-owned
    # lines surface the batch's approved_by/on on the receipt instead.
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_on = fields.Datetime(readonly=True, copy=False)
    locked_by = fields.Many2one('res.users', readonly=True, copy=False)
    locked_on = fields.Datetime(readonly=True, copy=False)
    component_ids = fields.One2many(
        'sl.bonus.batch.line.component', 'line_id', string='Calculation Breakdown',
    )

    # NB: no SQL _sql_constraints — the (employee, period) uniqueness is too
    # rich for a single SQL UNIQUE (needs year(period_start), month(period_start))
    # so it is enforced in Python via _check_unique_employee_period below.

    # ─────────────────────────────────────────────────────────────────
    #  Computed fields
    # ─────────────────────────────────────────────────────────────────
    @api.depends('batch_id')
    def _compute_is_independent(self):
        for rec in self:
            rec.is_independent = not bool(rec.batch_id)

    @api.depends('batch_id', 'batch_id.period_start', 'batch_id.period_end')
    def _compute_period_fields(self):
        """When attached to a batch, mirror the batch's period.

        For independent lines this compute is a no-op (readonly=False on the
        field means user-entered values stick); we only fill from the batch.
        """
        for rec in self:
            if rec.batch_id:
                rec.period_start = rec.batch_id.period_start
                rec.period_end = rec.batch_id.period_end

    @api.depends('batch_id', 'batch_id.company_id', 'batch_id.currency_id')
    def _compute_company_currency(self):
        for rec in self:
            if rec.batch_id:
                rec.company_id = rec.batch_id.company_id
                rec.currency_id = rec.batch_id.currency_id

    @api.depends('period_start')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = rec.period_start.strftime('%Y-%m') if rec.period_start else ''

    @api.depends('period_start')
    @api.depends_context('lang')
    def _compute_period_display(self):
        lang = self.env.context.get('lang') or self.env.user.lang or 'en_US'
        for rec in self:
            rec.period_display = _format_month_localized(rec.period_start, lang)

    @api.onchange('period_start')
    def _onchange_period_start_normalize(self):
        """For independent lines, snap period to first/last day of the month.

        Only applies when the line has no batch (batch-owned lines mirror the
        batch and its `period_start` is already normalized).
        """
        for rec in self:
            if rec.batch_id or not rec.period_start:
                continue
            ps = rec.period_start
            rec.period_start = date(ps.year, ps.month, 1)
            rec.period_end = date(ps.year, ps.month, monthrange(ps.year, ps.month)[1])

    # ─────────────────────────────────────────────────────────────────
    #  Constraints
    # ─────────────────────────────────────────────────────────────────
    @api.constrains('period_start', 'period_end', 'company_id', 'currency_id')
    def _check_required_after_compute(self):
        """Enforce required-ness for fields that are computed-stored.

        These fields aren't declared `required=True` because Odoo creates
        computed-stored columns with no value at INSERT (the compute runs
        AFTER insert). Enforcing required at the field would put NOT NULL on
        the column and break the standard create flow. Instead we validate
        here, which fires after the compute has filled the values.
        """
        for rec in self:
            missing = []
            if not rec.period_start:
                missing.append('period_start')
            if not rec.period_end:
                missing.append('period_end')
            if not rec.company_id:
                missing.append('company_id')
            if not rec.currency_id:
                missing.append('currency_id')
            if missing:
                raise ValidationError(_(
                    "Bonus line is missing required field(s): %s. "
                    "Independent lines must specify period_start; "
                    "batch-owned lines should auto-fill from the batch."
                ) % ', '.join(missing))

    @api.constrains('employee_id', 'period_start', 'company_id')
    def _check_unique_employee_period(self):
        """One bonus line per (employee, year-month, company), batch-owned or not.

        Replaces the old SQL UNIQUE(batch_id, employee_id) which was insufficient
        once independent lines and batch-owned lines could coexist for the same
        (employee, month).
        """
        for rec in self:
            if not rec.employee_id or not rec.period_start:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('company_id', '=', rec.company_id.id),
                ('period_start', '>=', date(rec.period_start.year, rec.period_start.month, 1)),
                ('period_start', '<=', date(
                    rec.period_start.year, rec.period_start.month,
                    monthrange(rec.period_start.year, rec.period_start.month)[1])),
            ]
            other = self.sudo().search(domain, limit=1)
            if other:
                where = (
                    _("Batch '%s'") % other.batch_id.name
                    if other.batch_id
                    else _("an independent bonus line")
                )
                raise ValidationError(_(
                    "Employee %(emp)s already has a bonus line for %(month)s "
                    "in %(where)s. Each employee may have at most one bonus per month."
                ) % {
                    'emp': rec.employee_id.name,
                    'month': rec.period_start.strftime('%Y-%m'),
                    'where': where,
                })

    # ─────────────────────────────────────────────────────────────────
    #  Permission helpers
    # ─────────────────────────────────────────────────────────────────
    def _is_admin(self):
        return self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
            or self.env.user.has_group('base.group_system')

    def _is_hr(self):
        return self._is_admin() \
            or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')

    # ─────────────────────────────────────────────────────────────────
    #  Write / unlink policy (covers batch-owned AND independent lines)
    # ─────────────────────────────────────────────────────────────────
    def write(self, vals):
        for rec in self:
            # Allow internal sync fields & chatter follower writes silently.
            internal_keys = {'message_follower_ids', 'message_main_attachment_id', 'state'}
            touched = set(vals.keys()) - internal_keys
            if not touched:
                continue
            # Batch-owned: gate on batch state (preserves prior behavior).
            if rec.batch_id:
                if rec.batch_id.state == 'approved' and not rec._is_admin():
                    raise AccessError(_("Approved batches are read-only. Contact an admin."))
                if rec.batch_id.state == 'locked' and not rec._is_admin():
                    raise AccessError(_("Locked batches are read-only."))
            else:
                # Independent: gate on the line's own state.
                if rec.state == 'approved' and not rec._is_admin():
                    raise AccessError(_("Approved bonus lines are read-only. Contact an admin."))
                if rec.state == 'locked' and not rec._is_admin():
                    raise AccessError(_("Locked bonus lines are read-only."))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.batch_id:
                # Original policy for batch-owned lines.
                if rec.batch_id.state in ('approved', 'locked') and not rec._is_admin():
                    raise UserError(_(
                        "Cannot delete this bonus line: batch '%(batch)s' is %(state)s. "
                        "Approved / locked batches are read-only."
                    ) % {'batch': rec.batch_id.name, 'state': rec.batch_id.state})
                if rec.batch_id.state in ('computed', 'hr_review') and not rec._is_admin():
                    raise UserError(_(
                        "Bonus lines can only be deleted while the batch is in Draft or Data Ready. "
                        "Recompute the batch instead to refresh it."
                    ))
            else:
                # Independent line policy: HR can delete draft; admin can delete
                # anything except locked.
                if rec.state == 'locked' and not rec._is_admin():
                    raise UserError(_("Locked bonus lines cannot be deleted."))
                if rec.state in ('approved',) and not rec._is_admin():
                    raise UserError(_("Approved bonus lines can only be deleted by Admin."))
            if not (rec._is_hr() or rec._is_admin()):
                raise AccessError(_(
                    "You don't have permission to delete bonus lines. Contact HR / Admin."
                ))
        return super().unlink()

    # ─────────────────────────────────────────────────────────────────
    #  Create-time defaults & onchange
    # ─────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        # For independent lines (no batch_id), make sure period_start/end are
        # snapped to the calendar month — the calculator and the duplicate
        # check assume month-aligned periods.
        for v in vals_list:
            if not v.get('batch_id') and v.get('period_start'):
                ps = fields.Date.to_date(v['period_start'])
                v['period_start'] = date(ps.year, ps.month, 1)
                if not v.get('period_end'):
                    v['period_end'] = date(
                        ps.year, ps.month, monthrange(ps.year, ps.month)[1]
                    )
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────
    #  Independent-line workflow buttons
    # ─────────────────────────────────────────────────────────────────
    def action_compute(self):
        """Calculator-driven compute for INDEPENDENT lines only.

        Batch-owned lines are recomputed via ``sl.bonus.batch.action_compute``,
        which gives a single transaction for the whole batch. Independent
        lines have their own button.
        """
        Calc = self.env['sl.bonus.calculator'].sudo()
        Component = self.env['sl.bonus.batch.line.component'].sudo()
        for rec in self:
            if rec.batch_id:
                raise UserError(_(
                    "This line is part of batch '%s'. Recompute the batch instead."
                ) % rec.batch_id.name)
            if not rec._is_hr():
                raise AccessError(_("Only HR Manager / Admin can compute bonus lines."))
            if rec.state not in ('draft', 'computed'):
                raise UserError(_(
                    "Compute is only allowed in Draft or Computed states. "
                    "Reset the line to draft first."
                ))
            if not rec.employee_id or not rec.period_start or not rec.period_end:
                raise UserError(_("Employee, period start and period end are required."))
            result = Calc.calculate_for_employee(rec.employee_id, rec.period_start, rec.period_end)
            line_vals = dict(result['line_vals'])
            # Strip employee_id (already set); the calculator returns it.
            line_vals.pop('employee_id', None)
            # Preserve manual override: if one exists, keep bonus_amount.
            has_override = bool(rec.manual_override_reason)
            if has_override:
                overridden = rec.manual_override_amount
                line_vals['bonus_amount'] = overridden
            rec.sudo().write({**line_vals, 'state': 'computed'})
            # Refresh components.
            if rec.component_ids:
                rec.component_ids.sudo().unlink()
            if result.get('components'):
                Component.create([
                    dict(c, line_id=rec.id) for c in result['components']
                ])
            rec.message_post(body=_("Bonus line computed by %s.") % self.env.user.name)
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=rec._name, res_id=rec.id, action='compute',
                old_value='', new_value=str(rec.computed_amount),
                reason='Independent line compute',
                employee_id=rec.employee_id.id, batch_id=False,
            )

    def action_approve(self):
        """Approve INDEPENDENT line. (Batch-owned lines follow the batch.)"""
        for rec in self:
            if rec.batch_id:
                raise UserError(_(
                    "This line is part of batch '%s'. Approve the batch instead."
                ) % rec.batch_id.name)
            if not rec._is_hr():
                raise AccessError(_("Only HR Manager / Admin can approve a bonus line."))
            if rec.state != 'computed':
                raise UserError(_("Only Computed lines can be approved."))
            rec.sudo().write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
            rec.message_post(body=_("Bonus line approved by %s.") % self.env.user.name)
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=rec._name, res_id=rec.id, action='approve',
                old_value='computed', new_value='approved',
                reason='Independent line approval',
                employee_id=rec.employee_id.id, batch_id=False,
            )

    def action_lock(self):
        """Lock INDEPENDENT line. Admin only. (Batch-owned lines follow the batch.)"""
        for rec in self:
            if rec.batch_id:
                raise UserError(_(
                    "This line is part of batch '%s'. Lock the batch instead."
                ) % rec.batch_id.name)
            if not rec._is_admin():
                raise AccessError(_("Only Admin can lock a bonus line."))
            if rec.state != 'approved':
                raise UserError(_("Only Approved lines can be locked."))
            rec.sudo().write({
                'state': 'locked',
                'locked_by': self.env.user.id,
                'locked_on': fields.Datetime.now(),
            })
            rec.message_post(body=_("Bonus line locked by %s.") % self.env.user.name)
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=rec._name, res_id=rec.id, action='lock',
                old_value='approved', new_value='locked',
                reason='Independent line lock',
                employee_id=rec.employee_id.id, batch_id=False,
            )

    def action_reset_to_draft(self):
        """Reset INDEPENDENT line back to draft. Admin only when approved/locked."""
        for rec in self:
            if rec.batch_id:
                raise UserError(_(
                    "This line is part of batch '%s'. Reset the batch instead."
                ) % rec.batch_id.name)
            if rec.state in ('approved', 'locked') and not rec._is_admin():
                raise AccessError(_("Only Admin can reset an approved / locked line."))
            if not rec._is_hr():
                raise AccessError(_("Only HR Manager / Admin can reset bonus lines."))
            old_state = rec.state
            rec.sudo().write({'state': 'draft'})
            rec.message_post(body=_("Bonus line reset to draft by %s.") % self.env.user.name)
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=rec._name, res_id=rec.id, action='reset_to_draft',
                old_value=old_state, new_value='draft',
                reason='Independent line reset',
                employee_id=rec.employee_id.id, batch_id=False,
            )

    # ─────────────────────────────────────────────────────────────────
    #  Manual override (works for batch-owned AND independent lines)
    # ─────────────────────────────────────────────────────────────────
    def action_apply_manual_override(self, new_amount, reason):
        """Apply a manual override with mandatory reason and audit log."""
        self.ensure_one()
        if not self._is_hr():
            raise AccessError(_("Only HR Manager / Admin can override a bonus amount."))
        if self.batch_id:
            if self.batch_id.state not in ('computed', 'hr_review', 'approved'):
                raise UserError(_("Manual override is only allowed in Computed, HR Review, or Approved states."))
            if self.batch_id.state == 'approved' and not self._is_admin():
                raise AccessError(_("Only Admin can override an approved line."))
        else:
            if self.state not in ('computed', 'approved'):
                raise UserError(_("Manual override is only allowed in Computed or Approved states."))
            if self.state == 'approved' and not self._is_admin():
                raise AccessError(_("Only Admin can override an approved line."))
        if not reason or not reason.strip():
            raise ValidationError(_("A reason is mandatory for any manual override."))
        old_amount = self.bonus_amount
        self.sudo().write({
            'manual_override_amount': new_amount,
            'manual_override_reason': reason,
            'manual_override_by': self.env.user.id,
            'manual_override_on': fields.Datetime.now(),
            'bonus_amount': new_amount,
        })
        self.env['sl.bonus.audit.log'].sudo().log_change(
            model=self._name,
            res_id=self.id,
            action='manual_override',
            old_value=str(old_amount),
            new_value=str(new_amount),
            reason=reason,
            employee_id=self.employee_id.id,
            batch_id=self.batch_id.id if self.batch_id else False,
        )
        self.message_post(body=_(
            "Manual override: %(old)s → %(new)s. Reason: %(reason)s"
        ) % {'old': old_amount, 'new': new_amount, 'reason': reason})

    def action_open_manual_adjust(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sl.bonus.manual.adjust.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_line_id': self.id,
                'default_new_amount': self.bonus_amount,
            },
        }

    def action_clear_override(self):
        self.ensure_one()
        if not self._is_hr():
            raise AccessError(_("Only HR Manager / Admin can clear an override."))
        # Lock check.
        if self.batch_id and self.batch_id.state == 'locked' and not self._is_admin():
            raise AccessError(_("Locked batches are read-only."))
        if not self.batch_id and self.state == 'locked' and not self._is_admin():
            raise AccessError(_("Locked bonus lines are read-only."))
        old = self.bonus_amount
        self.sudo().write({
            'manual_override_amount': 0.0,
            'manual_override_reason': False,
            'manual_override_by': False,
            'manual_override_on': False,
            'bonus_amount': self.computed_amount,
        })
        self.env['sl.bonus.audit.log'].sudo().log_change(
            model=self._name, res_id=self.id,
            action='clear_override', old_value=str(old),
            new_value=str(self.computed_amount),
            reason='Cleared by user',
            employee_id=self.employee_id.id,
            batch_id=self.batch_id.id if self.batch_id else False,
        )

    # ─────────────────────────────────────────────────────────────────
    #  Receipt PDF action
    # ─────────────────────────────────────────────────────────────────
    def action_print_receipt(self):
        """Render the employee bonus receipt PDF.

        Visibility rules are enforced both in the form (button invisible
        when state not in approved/locked) AND here, so direct calls or
        URL fishing cannot bypass them.
        """
        for rec in self:
            if rec.state not in ('approved', 'locked'):
                raise UserError(_(
                    "Receipt can only be printed for Approved or Locked bonus lines."
                ))
        return self.env.ref(
            'sl_monthly_bonus.action_report_sl_bonus_receipt'
        ).report_action(self)

    # ─────────────────────────────────────────────────────────────────
    #  Helper called by the batch when its state changes — propagates to
    #  the child lines so users see a consistent state column.
    # ─────────────────────────────────────────────────────────────────
    def _sync_state_from_batch(self):
        for rec in self:
            if not rec.batch_id:
                continue
            target = _BATCH_TO_LINE_STATE.get(rec.batch_id.state, 'draft')
            if rec.state != target:
                rec.sudo().write({'state': target})


class SlBonusBatchLineComponent(models.Model):
    """Per-line itemized calculation breakdown (for transparency in self-service & audit)."""
    _name = 'sl.bonus.batch.line.component'
    _description = 'Bonus Calculation Component'
    _order = 'line_id, sequence'

    line_id = fields.Many2one('sl.bonus.batch.line', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(string='Label', required=True)
    value = fields.Char(string='Value', required=True)
    note = fields.Char(string='Note')
