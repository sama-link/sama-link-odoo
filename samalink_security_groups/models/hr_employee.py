from odoo import models, api, fields, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    current_leave_id = fields.Many2one('hr.leave.type', compute='_compute_current_leave', string="Current Time Off Type",
                                       groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    has_work_entries = fields.Boolean(compute='_compute_has_work_entries', groups="base.group_system,hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    calendar_mismatch = fields.Boolean(related='contract_id.calendar_mismatch', groups="base.group_system,hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_ids = fields.One2many(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_exception_decoration = fields.Selection(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_summary = fields.Text(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_exception_icon = fields.Char(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_state = fields.Selection(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_type_icon = fields.Char(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")
    activity_type_id = fields.Many2one(groups="hr.group_hr_user,samalink_security_groups.group_samalink_employee")

    # Override manager fields to ensure they are readable by all internal users 
    # to prevent Access Errors during record rule evaluation
    attendance_manager_id = fields.Many2one('res.users', string='Attendance Manager', groups="base.group_user")
    leave_manager_id = fields.Many2one('res.users', string='Time Off Manager', groups="base.group_user")
    coach_id = fields.Many2one('hr.employee', string='Coach', groups="base.group_user")

    def _sl_can_open_employee_card(self, user):
        """Whether `user` may navigate to this employee's card (org chart
        nodes and many2one internal links end up in get_formview_action).

        Allowed: HR officers / Samalink administrators / system admins, the
        employee themself, and managers for their own team (same relations as
        the hr_employee_rule_managers_all_teams record rule)."""
        self.ensure_one()
        if (user.has_group('hr.group_hr_user')
                or user.has_group('samalink_security_groups.group_samalink_administrator')
                or user.has_group('base.group_system')):
            return True
        record = self.sudo()
        if record.user_id.id == user.id:
            return True
        if record.leave_manager_id.id == user.id or record.attendance_manager_id.id == user.id:
            return True
        employee = user.employee_id
        if not employee:
            return False
        if record.coach_id.id == employee.id:
            return True
        return bool(record.search_count(
            [('id', '=', record.id), ('id', 'child_of', employee.id)]))

    def get_formview_action(self, access_uid=None):
        """Block opening other employees' cards (e.g. managers clicked in the
        My Info hierarchy) for users outside the allowed relations above."""
        user = (self.env['res.users'].browse(access_uid)
                if access_uid else self.env.user)
        if len(self) == 1 and not self._sl_can_open_employee_card(user):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Restricted'),
                    'message': _("You don't have access to this employee's card."),
                },
            }
        return super().get_formview_action(access_uid=access_uid)

    @api.model
    def action_open_my_employee(self):
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if not employee:
            raise UserError("No employee record linked to your user.")
        action = self.env.ref('samalink_security_groups.hr_open_view_employee_form_my').sudo().read()[0]
        action['res_id'] = employee.id
        return action