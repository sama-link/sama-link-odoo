import logging
from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    def action_approve(self, check_state=True):
        is_sl_admin = self.env.user.has_group('samalink_security_groups.group_samalink_administrator')
        is_sl_general_manager = self.env.user.has_group('samalink_security_groups.group_sl_general_manager')
        is_sl_timeoff_mgr = self.env.user.has_group('samalink_security_groups.group_sl_timeoff_manager')
        is_sl_hr_officer = self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer')

        if not is_sl_admin and not is_sl_hr_officer:
            for record in self:
                if record.employee_id.user_id == self.env.user:
                    raise UserError("You cannot approve your own time off.")

        # Check: only the leave_manager_id or parent_id (General Manager) or HR Officer can approve
        if not is_sl_admin and not is_sl_general_manager and not is_sl_hr_officer:
            for record in self:
                emp = record.sudo().employee_id
                current_leave_mgr = emp.leave_manager_id
                if current_leave_mgr and self.env.user != current_leave_mgr:
                    raise UserError("You cannot approve leaves for employees you do not manage.")

        # Time Off Managers / General Managers are not Time Off Officers
        # (hr_holidays.group_hr_holidays_user), which Odoo's core approval
        # checks require. The SamaLink role checks above are the real
        # authorisation, so run the core approval as superuser: hr_holidays
        # already treats the superuser as an officer in write() and
        # _check_approval_update() (and see _check_double_validation_rules
        # below).
        #
        # This used to temporarily ADD the user to the Time Off Officer group
        # and REMOVE it again in a finally block, together with
        # hr.group_hr_user which that group implies. It never checked whether
        # the user already had those groups, so anyone holding "Officer:
        # Manage all employees" / Time Off Officer legitimately (granted by
        # hand, or implied by the SamaLink HR Officer group) lost them the
        # first time they approved a request. The group juggling also cleared
        # the whole registry cache twice per approval. No group is touched
        # any more.
        if is_sl_timeoff_mgr or is_sl_general_manager:
            return super(HrLeave, self.sudo()).action_approve(check_state)
        return super().action_approve(check_state)

    def _check_double_validation_rules(self, employees, state):
        # hr_holidays skips _check_approval_update() for the superuser but not
        # this sibling check (it looks at the real user's groups). Mirror the
        # superuser rule so the sudo() approval above also works for
        # "both"-validation leave types.
        if self.env.su:
            return
        return super()._check_double_validation_rules(employees, state)
