# -*- coding: utf-8 -*-
from odoo import api, models


class LeaveReportCalendar(models.Model):
    _inherit = 'hr.leave.report.calendar'

    @api.depends('employee_id.name', 'leave_id')
    def _compute_name(self):
        """Core can set name from employee_id.name which is False; += then crashes."""
        for leave in self:
            name = leave.employee_id.name or ''
            if self.env.user.has_group('hr_holidays.group_hr_holidays_user'):
                type_name = leave.leave_id.holiday_status_id.name or ''
                name = f"{name} {type_name}".strip()
            duration = leave.sudo().leave_id.duration_display
            if duration:
                name = f"{name}: {duration}" if name else str(duration)
            leave.name = name
