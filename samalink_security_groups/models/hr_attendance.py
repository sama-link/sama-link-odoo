from odoo import models
from odoo.exceptions import UserError


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def write(self, vals):
        restricted_fields = {'check_in', 'check_out', 'employee_id'}
        modifying_restricted = any(f in vals for f in restricted_fields)

        if modifying_restricted:
            is_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator') or self.env.user.has_group('base.group_system')
            
            # Allow system operations (like native check-out) which use sudo()
            if not is_admin and not self.env.su:
                raise UserError("Only Administrators are allowed to manually edit the Employee, Check-In, or Check-Out fields.")
        
        return super().write(vals)


    def action_approve_overtime(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')
        is_sl_hr_officer = self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer')

        if not is_sl_admin and not is_sl_hr_officer:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot approve overtime for yourself.")

        if not is_sl_admin and not is_sl_general_manager and not is_sl_hr_officer:
            for record in self:
                current_employee_manager = record.sudo().employee_id.attendance_manager_id
                if current_employee_manager and self.env.user != current_employee_manager:
                    raise UserError("You cannot approve overtime for employees you do not manage.")
        return super().action_approve_overtime()

    def action_refuse_overtime(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')
        is_sl_hr_officer = self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer')

        if not is_sl_admin and not is_sl_hr_officer:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot refuse overtime for yourself.")

        if not is_sl_admin and not is_sl_general_manager and not is_sl_hr_officer:
            for record in self:
                current_employee_manager = record.sudo().employee_id.attendance_manager_id
                if current_employee_manager and self.env.user != current_employee_manager:
                    raise UserError("You cannot refuse overtime for employees you do not manage.")
        return super().action_refuse_overtime()