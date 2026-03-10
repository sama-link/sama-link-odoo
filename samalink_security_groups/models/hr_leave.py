import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_approve(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')
        is_sl_timeoff_mgr = self.env.user.has_group('samalink_security_groups.group_sl_timeoff_manager')

        if not is_sl_admin:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot approve your own time off.")

        # Check: only the leave_manager_id or parent_id (General Manager) can approve
        if not is_sl_admin and not is_sl_general_manager:
            for record in self:
                emp = record.sudo().employee_id
                current_leave_mgr = emp.leave_manager_id
                if current_leave_mgr and self.env.user != current_leave_mgr:
                    raise UserError("You cannot approve leaves for employees you do not manage.")

        # Temporarily elevate permissions for Odoo's super().action_approve()
        # which requires group_hr_holidays_user
        needs_elevation = is_sl_timeoff_mgr or is_sl_general_manager
        timeoff_group = self.env.ref('hr_holidays.group_hr_holidays_user')

        if needs_elevation:
            timeoff_group.sudo().write({'users': [(4, self.env.user.id)]})

        try:
            res = super().action_approve()
        finally:
            if needs_elevation and self.env.user.has_group('hr_holidays.group_hr_holidays_user'):
                timeoff_group.sudo().write({'users': [(3, self.env.user.id)]})
                # Also clean up implicit hr.group_hr_user if added
                employee_group = self.env.ref('hr.group_hr_user')
                employee_group.sudo().write({'users': [(3, self.env.user.id)]})

        return res