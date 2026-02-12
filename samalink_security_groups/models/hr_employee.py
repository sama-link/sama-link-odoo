from odoo import models, api, fields
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

    @api.model
    def action_open_my_employee(self):
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if not employee:
            raise UserError("No employee record linked to your user.")
        action = self.env.ref('samalink_security_groups.hr_open_view_employee_form_my').sudo().read()[0]
        action['res_id'] = employee.id
        return action