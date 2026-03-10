from odoo import models
from odoo.exceptions import UserError


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def action_approve_overtime(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')

        if not is_sl_admin:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot approve overtime for yourself.")

        if not is_sl_admin and not is_sl_general_manager:
            for record in self:
                current_employee_manager = record.sudo().employee_id.attendance_manager_id
                if current_employee_manager and self.env.user != current_employee_manager:
                    raise UserError("You cannot approve overtime for employees you do not manage.")
        return super().action_approve_overtime()

    def action_refuse_overtime(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')

        if not is_sl_admin:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot refuse overtime for yourself.")

        if not is_sl_admin and not is_sl_general_manager:
            for record in self:
                current_employee_manager = record.sudo().employee_id.attendance_manager_id
                if current_employee_manager and self.env.user != current_employee_manager:
                    raise UserError("You cannot refuse overtime for employees you do not manage.")
        return super().action_refuse_overtime()