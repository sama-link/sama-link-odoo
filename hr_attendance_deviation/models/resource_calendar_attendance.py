from odoo import models, fields, api
from odoo.addons.hr_attendance_deviation.tools import Converter


class ResourceCalendarAttendance(models.Model):
    _inherit = 'resource.calendar.attendance'

    @api.depends('calendar_id.name', 'hour_from', 'hour_to')
    def _compute_display_name(self):
        for record in self:
            default_name = record.name
            hour_from_time, hour_to_time = record._get_time_objects()
            record.display_name = f"{record.calendar_id.name} ({hour_from_time.strftime('%I:%M %p')} - {hour_to_time.strftime('%I:%M %p')}) {default_name}"

    def _get_time_objects(self):
        self.ensure_one()
        hour_from_time = Converter.float_to_time_obj(self.hour_from)
        hour_to_time = Converter.float_to_time_obj(self.hour_to)
        return hour_from_time, hour_to_time 