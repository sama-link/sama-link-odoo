from odoo import _, fields, models, Command


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    overtime_approval_reason = fields.Text(
        string='Overtime Reason', copy=False, tracking=True,
        help='Reason entered by the approver when this overtime was approved.')

    def action_approve_overtime(self):
        """ Require a mandatory reason (via wizard) before approving overtime.

        Employees on the Overtime Approval Exceptions list keep the old
        one-click behaviour and are approved directly. Wizard confirmations
        come back with the context flag and go straight through. """
        if self.env.context.get('sl_skip_overtime_reason'):
            return super().action_approve_overtime()
        exempt_employee_ids = set(
            self.env['sl.overtime.approval.exception'].sudo().search([]).employee_id.ids)
        need_reason = self.filtered(lambda att: att.employee_id.id not in exempt_employee_ids)
        direct = self - need_reason
        if direct:
            # Old logic: approve immediately (permission checks run in super).
            super(HrAttendance, direct).action_approve_overtime()
        if need_reason:
            return {
                'name': _('Overtime Approval Reason'),
                'type': 'ir.actions.act_window',
                'res_model': 'sl.overtime.approval.reason.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_attendance_ids': [Command.set(need_reason.ids)]},
            }
        return True
