from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError


STATE_SELECTION = [
    ('draft', 'Draft'),
    ('data_ready', 'Data Ready'),
    ('computed', 'Computed'),
    ('hr_review', 'HR Review'),
    ('approved', 'Approved'),
    ('locked', 'Locked'),
]


class SlBonusStateChangeWizard(models.TransientModel):
    """Admin-only emergency tool to flip a batch into any state with a written
    reason. Every change is recorded in sl.bonus.audit.log. Use only when the
    batch is stuck (e.g. mid-state crash, recovered backup, etc.); the normal
    workflow buttons should be the default path.
    """
    _name = 'sl.bonus.state.change.wizard'
    _description = 'Admin Manual Batch State Change'

    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Batch', required=True, ondelete='cascade',
    )
    current_state = fields.Selection(
        STATE_SELECTION, related='batch_id.state', readonly=True,
    )
    new_state = fields.Selection(STATE_SELECTION, string='New State', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_apply(self):
        self.ensure_one()
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_("Only Admin can manually change a batch state."))
        if not self.reason or not self.reason.strip():
            raise ValidationError(_("A reason is mandatory."))
        if self.new_state == self.batch_id.state:
            raise ValidationError(_("The new state is the same as the current state."))
        old_state = self.batch_id.state
        # Keep audit-relevant fields aligned with the new state.
        vals = {'state': self.new_state}
        if self.new_state == 'approved':
            vals.update({
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
        elif self.new_state == 'locked':
            vals.update({
                'locked_by': self.env.user.id,
                'locked_on': fields.Datetime.now(),
            })
        elif self.new_state == 'draft':
            vals.update({
                'approved_by': False, 'approved_on': False,
                'locked_by': False, 'locked_on': False,
            })
        self.batch_id.sudo().write(vals)
        self.env['sl.bonus.audit.log'].sudo().log_change(
            model='sl.bonus.batch',
            res_id=self.batch_id.id,
            action='admin_state_change',
            old_value=old_state,
            new_value=self.new_state,
            reason=self.reason,
            batch_id=self.batch_id.id,
        )
        self.batch_id.message_post(body=_(
            "Admin state change: %(old)s → %(new)s. Reason: %(reason)s"
        ) % {'old': old_state, 'new': self.new_state, 'reason': self.reason})
        return {'type': 'ir.actions.act_window_close'}
