import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_approve(self):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        current_employee_manager = self.sudo().employee_id.leave_manager_id
        if is_sl_admin and self.env.user != current_employee_manager:
            raise UserError("You cannot approve leaves for employees you do not manage.")

        is_sl_manager = self.env.user.has_group('samalink_security_groups.group_samalink_manager')
        timeoff_group = self.env.ref('hr_holidays.group_hr_holidays_user')
        if is_sl_manager:
            timeoff_group.sudo().write({'users': [(4, self.env.user.id)]})
        res = super().action_approve()
        if is_sl_manager and self.env.user.has_group('hr_holidays.group_hr_holidays_user'):
            timeoff_group.sudo().write({'users': [(3, self.env.user.id)]})
            employee_group = self.env.ref('hr.group_hr_user')
            employee_group.sudo().write({'users': [(3, self.env.user.id)]})
        return res