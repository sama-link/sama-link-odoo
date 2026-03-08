from odoo import models, api, fields
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

# Mapping: employee field → (security group XML ID, field type)
# field type: 'user' means the field stores res.users ID directly
#             'employee' means the field stores hr.employee ID (need to get user_id)
MANAGER_FIELD_TO_GROUP = {
    'parent_id': ('samalink_security_groups.group_sl_general_manager', 'employee'),
    'coach_id': ('samalink_security_groups.group_sl_coach_manager', 'employee'),
    'leave_manager_id': ('samalink_security_groups.group_sl_timeoff_manager', 'user'),
    'attendance_manager_id': ('samalink_security_groups.group_sl_attendance_manager', 'user'),
}


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

    @api.model
    def action_open_my_employee(self):
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if not employee:
            raise UserError("No employee record linked to your user.")
        action = self.env.ref('samalink_security_groups.hr_open_view_employee_form_my').sudo().read()[0]
        action['res_id'] = employee.id
        return action

    def write(self, vals):
        # Capture OLD manager users before write (for ALL four fields, not just changed ones)
        old_manager_users = self._collect_old_manager_users(vals)

        res = super().write(vals)

        # Auto-assign new managers
        self._auto_assign_manager_groups(vals)

        # Auto-remove: for every old manager user, check ALL four fields
        self._auto_remove_orphan_groups(old_manager_users)

        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for vals in vals_list:
            records._auto_assign_manager_groups(vals)
        return records

    def _collect_old_manager_users(self, vals):
        """Collect the old manager users for fields that are being changed."""
        old_users = set()
        for field_name, (group_xmlid, field_type) in MANAGER_FIELD_TO_GROUP.items():
            if field_name not in vals:
                continue
            for rec in self:
                old_val = rec.sudo()[field_name]
                if old_val:
                    if field_type == 'user':
                        old_users.add(old_val)  # res.users record
                    else:
                        if old_val.user_id:
                            old_users.add(old_val.user_id)  # hr.employee → user
        return old_users

    def _auto_assign_manager_groups(self, vals):
        """Auto-assign security groups when manager fields are set on employees."""
        for field_name, (group_xmlid, field_type) in MANAGER_FIELD_TO_GROUP.items():
            if field_name not in vals:
                continue
            manager_value = vals[field_name]
            if not manager_value:
                continue

            try:
                group = self.env.ref(group_xmlid)
            except ValueError:
                _logger.warning("Group %s not found, skipping auto-assign.", group_xmlid)
                continue

            # Resolve the user from the field value
            if field_type == 'user':
                user = self.env['res.users'].sudo().browse(manager_value)
            else:
                employee = self.env['hr.employee'].sudo().browse(manager_value)
                user = employee.user_id

            if user and user.exists() and not user.has_group(group_xmlid):
                _logger.info(
                    "Auto-assigning group '%s' to user '%s' (set as %s)",
                    group.name, user.name, field_name,
                )
                group.sudo().write({'users': [(4, user.id)]})

    def _auto_remove_orphan_groups(self, old_manager_users):
        """For each old manager user, check ALL four manager fields.
        If the user is no longer referenced in ANY employee for a given field,
        remove the corresponding group.
        Also handle group_samalink_manager: remove it if the user has no
        remaining manager role at all."""
        if not old_manager_users:
            return

        Employee = self.env['hr.employee'].sudo()

        for old_user in old_manager_users:
            if not old_user or not old_user.exists():
                continue

            # Find the employee record for this user (needed for parent_id/coach_id checks)
            manager_employee = Employee.search([('user_id', '=', old_user.id)], limit=1)

            any_role_remaining = False

            for field_name, (group_xmlid, field_type) in MANAGER_FIELD_TO_GROUP.items():
                try:
                    group = self.env.ref(group_xmlid)
                except ValueError:
                    continue

                # Check if user still manages anyone via this field
                if field_type == 'user':
                    remaining = Employee.search_count([(field_name, '=', old_user.id)])
                else:
                    if manager_employee:
                        remaining = Employee.search_count([(field_name, '=', manager_employee.id)])
                    else:
                        remaining = 0

                if remaining > 0:
                    any_role_remaining = True
                elif old_user.has_group(group_xmlid):
                    _logger.info(
                        "Auto-removing group '%s' from user '%s' (no longer %s for any employee)",
                        group.name, old_user.name, field_name,
                    )
                    group.sudo().write({'users': [(3, old_user.id)]})