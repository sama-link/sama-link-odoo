import logging
import pytz
from datetime import datetime, time, timedelta
from odoo import models, fields, api, exceptions


_logger = logging.getLogger(__name__)

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    middleware_id = fields.Many2one(
        'hr.attendance.middleware',
        string='Middleware Record',
        help='Link to the middleware record associated with this attendance record.',
        readonly=True,
    )
    late_check_in = fields.Float(
        string='Late',
        help='Time in hours that the employee checked in late.',
        readonly=True,
    )
    late_check_in_approved = fields.Boolean(
        string='Late Check-In Approved',
        default=False,
        help='Indicates whether the late check-in has been approved.',
        readonly=True,
    )
    early_check_out = fields.Float(
        string='Early',
        help='Time in hours that the employee checked out early.',
        readonly=True,
    )
    early_check_out_approved = fields.Boolean(
        string='Early Check-Out Approved',
        default=False,
        help='Indicates whether the early check-out has been approved.',
        readonly=True,
    )

    def get_late_days_hours(self):
        allowed_late_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_late_minutes', default=30)
        allowed_late_hours = int(allowed_late_minutes) / 60.0
        late_attendances = self.filtered(lambda att: att.late_check_in > allowed_late_hours)
        late_days = len(late_attendances)
        late_hours = sum(late_attendances.mapped('late_check_in'))
        return {'late_days': late_days, 'late_hours': late_hours}

    def get_early_leaving_days_hours(self):
        allowed_early_leaving_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_early_leaving_minutes', default=15)
        allowed_early_leaving_hours = int(allowed_early_leaving_minutes) / 60.0
        early_leaving_attendances = self.filtered(lambda att: att.early_check_out > allowed_early_leaving_hours)
        early_leaving_days = len(early_leaving_attendances)
        early_leaving_hours = sum(early_leaving_attendances.mapped('early_check_out'))
        return {'early_leaving_days': early_leaving_days, 'early_leaving_hours': early_leaving_hours}