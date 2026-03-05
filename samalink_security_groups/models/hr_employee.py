from odoo import models, api, fields
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

# Mapping: employee field → security group XML ID
MANAGER_FIELD_TO_GROUP = {
    'parent_id': 'samalink_security_groups.group_sl_general_manager',
    'coach_id': 'samalink_security_groups.group_sl_coach_manager',
    'leave_manager_id': 'samalink_security_groups.group_sl_timeoff_manager',
    'attendance_manager_id': 'samalink_security_groups.group_sl_attendance_manager',
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
        res = super().write(vals)
        self._auto_assign_manager_groups(vals)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for vals in vals_list:
            records._auto_assign_manager_groups(vals)
        return records

    def _auto_assign_manager_groups(self, vals):
        """Auto-assign security groups when manager fields are set on employees."""
        for field_name, group_xmlid in MANAGER_FIELD_TO_GROUP.items():
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
            if field_name in ('leave_manager_id', 'attendance_manager_id'):
                # These are res.users fields — the value IS the user ID
                user = self.env['res.users'].sudo().browse(manager_value)
            elif field_name == 'parent_id':
                # parent_id is an hr.employee field — get the user from the employee
                employee = self.env['hr.employee'].sudo().browse(manager_value)
                user = employee.user_id
            elif field_name == 'coach_id':
                # coach_id is an hr.employee field — get the user from the employee
                employee = self.env['hr.employee'].sudo().browse(manager_value)
                user = employee.user_id

            if user and user.exists() and not user.has_group(group_xmlid):
                _logger.info(
                    "Auto-assigning group '%s' to user '%s' (set as %s)",
                    group.name, user.name, field_name,
                )
                group.sudo().write({'users': [(4, user.id)]})