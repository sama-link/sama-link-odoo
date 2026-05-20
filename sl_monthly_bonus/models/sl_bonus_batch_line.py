from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError


class SlBonusBatchLine(models.Model):
    """One bonus line per employee within a batch."""
    _name = 'sl.bonus.batch.line'
    _description = 'Monthly Bonus Batch Line'
    _order = 'batch_id desc, employee_id'
    _inherit = ['mail.thread']

    batch_id = fields.Many2one(
        'sl.bonus.batch', required=True, ondelete='cascade', string='Batch',
        index=True,
    )
    batch_state = fields.Selection(related='batch_id.state', store=True)
    company_id = fields.Many2one(related='batch_id.company_id', store=True)
    period_start = fields.Date(related='batch_id.period_start', store=True)
    period_end = fields.Date(related='batch_id.period_end', store=True)
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
    # Inputs by category (for transparency)
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
    # Outputs
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
    currency_id = fields.Many2one(
        'res.currency', related='batch_id.currency_id', store=True, readonly=True,
    )
    component_ids = fields.One2many(
        'sl.bonus.batch.line.component', 'line_id', string='Calculation Breakdown',
    )

    _sql_constraints = [
        ('uniq_batch_employee',
         'unique(batch_id, employee_id)',
         'An employee can only appear once per bonus batch.'),
    ]

    # ── Permission helpers ────────────────────────────────────────────
    def _is_admin(self):
        return self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
            or self.env.user.has_group('base.group_system')

    def _is_hr(self):
        return self._is_admin() \
            or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')

    def write(self, vals):
        # Block edits on approved/locked except manual override by admin
        for rec in self:
            if rec.batch_id.state in ('approved',) and not rec._is_admin():
                touched = set(vals.keys()) - {'message_follower_ids', 'message_main_attachment_id'}
                if touched:
                    raise AccessError(_("Approved batches are read-only. Contact an admin."))
            if rec.batch_id.state == 'locked' and not rec._is_admin():
                raise AccessError(_("Locked batches are read-only."))
        return super().write(vals)

    def unlink(self):
        """Allow line deletion only while the parent batch is in draft or data_ready,
        and only for HR Manager / Admin. Components cascade automatically.
        """
        # Admin can delete anything except locked.
        for rec in self:
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
            if not (rec._is_hr() or rec._is_admin()):
                raise AccessError(_(
                    "You don't have permission to delete bonus lines. Contact HR / Admin."
                ))
        return super().unlink()

    def action_apply_manual_override(self, new_amount, reason):
        """Apply a manual override with mandatory reason and audit log."""
        self.ensure_one()
        if not self._is_hr():
            raise AccessError(_("Only HR Manager / Admin can override a bonus amount."))
        if self.batch_id.state not in ('computed', 'hr_review', 'approved'):
            raise UserError(_("Manual override is only allowed in Computed, HR Review, or Approved states."))
        if self.batch_id.state == 'approved' and not self._is_admin():
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
            batch_id=self.batch_id.id,
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
        if self.batch_id.state == 'locked' and not self._is_admin():
            raise AccessError(_("Locked batches are read-only."))
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
            employee_id=self.employee_id.id, batch_id=self.batch_id.id,
        )


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
