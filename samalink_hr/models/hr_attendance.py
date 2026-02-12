from odoo import models, fields, api



class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    has_late_permission = fields.Boolean(string='Has Late Permission', compute='_compute_has_late_permission')
    work_location_id = fields.Many2one(related="employee_id.work_location_id", domain="[('address_id', '=', address_id)]")

    def _compute_has_late_permission(self):
        for attendance in self:
            date = attendance.check_in.date()
            late_permission = self.env['hr.leave'].search_count([
                ('employee_id', '=', attendance.employee_id.id),
                ('request_date_from', '=', date),
                ('state', '=', 'validate'),
                ('holiday_status_id.code', '=', 'LATE'),
            ])
            attendance.has_late_permission = bool(late_permission)

    def action_open_related_leave(self):
        self.ensure_one()
        date = self.check_in.date()
        hr_leave_id = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('request_date_from', '=', date),
            ('state', '=', 'validate'),
            ('holiday_status_id.code', '=', 'LATE'),
        ], limit=1)
        if hr_leave_id:
            action = self.env["ir.actions.actions"]._for_xml_id(
                "hr_holidays.hr_leave_action_my"
            )
            action['views'] = [(self.env.ref('hr_holidays.hr_leave_view_form').id, 'form')]
            action['res_id'] = hr_leave_id.id
            action['target'] = 'current'
            return action