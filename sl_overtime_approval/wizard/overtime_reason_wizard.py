from odoo import fields, models


class OvertimeApprovalReasonWizard(models.TransientModel):
    _name = 'sl.overtime.approval.reason.wizard'
    _description = 'Overtime Approval Reason Wizard'

    attendance_ids = fields.Many2many(
        'hr.attendance', string='Overtime Records', required=True, readonly=True)
    reason = fields.Text(string='Reason for Overtime', required=True)

    def action_confirm(self):
        self.ensure_one()
        attendances = self.attendance_ids
        attendances.write({'overtime_approval_reason': self.reason})
        # The context flag lets the approval pass through without re-opening the
        # wizard; the samalink permission checks still run inside the approval.
        return attendances.with_context(sl_skip_overtime_reason=True).action_approve_overtime()
