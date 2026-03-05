import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_approve(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')

        if not is_sl_admin and not is_sl_general_manager:
            for record in self:
                current_employee_manager = record.sudo().employee_id.leave_manager_id
                if current_employee_manager and self.env.user != current_employee_manager:
                    raise UserError("You cannot approve leaves for employees you do not manage.")

        is_sl_timeoff_mgr = self.env.user.has_group('samalink_security_groups.group_sl_timeoff_manager')
        timeoff_group = self.env.ref('hr_holidays.group_hr_holidays_user')
        if is_sl_timeoff_mgr:
            timeoff_group.sudo().write({'users': [(4, self.env.user.id)]})
        try:
            res = super().action_approve()
        finally:
            # Always clean up the temporary group elevation even if approval fails
            if is_sl_timeoff_mgr and self.env.user.has_group('hr_holidays.group_hr_holidays_user'):
                timeoff_group.sudo().write({'users': [(3, self.env.user.id)]})
                employee_group = self.env.ref('hr.group_hr_user')
                employee_group.sudo().write({'users': [(3, self.env.user.id)]})
        return res