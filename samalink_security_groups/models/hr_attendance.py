from odoo import models
from odoo.exceptions import UserError


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def action_approve_overtime(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        current_employee_manager = self.sudo().employee_id.attendance_manager_id
        if is_sl_admin and self.env.user != current_employee_manager:
            raise UserError("You cannot approve overtime for employees you do not manage.")
        return super().action_approve_overtime()