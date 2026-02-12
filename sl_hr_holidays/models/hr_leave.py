import logging
import calendar
from datetime import timedelta
from odoo import models, api, fields
from odoo.exceptions import ValidationError

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    request_date_from_period = fields.Selection([
        ('am', 'First Half'), ('pm', 'Second Half')],
        string="Date Period Start", default='am')

    @api.constrains('number_of_hours', 'resource_calendar_id', 'leave_type_request_unit')
    def _check_half_day_hours_limit(self):
        for record in self:
            half_day_hours = record.resource_calendar_id.hours_per_day / 2
            if (record.request_unit_half or record.request_unit_hours) and record.leave_type_request_unit == 'hour' and record.number_of_hours > half_day_hours:
                raise ValidationError(f"You can only request a half-day leave of up to {half_day_hours} hours and you requested {record.number_of_hours} hours for {record.name}.")

    
    def _get_hour_from_to(self, request_date_from, request_date_to, day_period=None):
        hour_from, hour_to = super()._get_hour_from_to(request_date_from, request_date_to, day_period=day_period)
        if self.request_unit_half:
            if hour_from and hour_to:
                hour_from, hour_to = self._half_day_hour_from_to(hour_from, hour_to, day_period)
            else:
                original_day_period = day_period
                day_period = 'morning' if day_period == 'afternoon' else 'afternoon'
                hour_from, hour_to = super()._get_hour_from_to(request_date_from, request_date_to, day_period=day_period)
                hour_from, hour_to = self._half_day_hour_from_to(hour_from, hour_to, original_day_period)
        return (hour_from, hour_to)

    def _half_day_hour_from_to(self, hour_from, hour_to, day_period):
        half_day_hours = self.resource_calendar_id.hours_per_day / 2
        if day_period == 'morning':
            hour_to = hour_from + half_day_hours
        elif day_period == 'afternoon':
            hour_from = hour_to - half_day_hours
        return (hour_from, hour_to)

    @api.constrains('employee_id', 'request_date_from', 'holiday_status_id')
    def _check_requests_limit(self):
        for record in self:
            if record.holiday_status_id.requests_limit > 0:
                first_day = record.request_date_from.replace(day=1)
                last_day = record.request_date_from.replace(day=calendar.monthrange(record.request_date_from.year, record.request_date_from.month)[1])
                domain = [
                    ('employee_id', '=', record.employee_id.id),
                    ('state', 'not in', ['refuse', 'cancel']),
                    ('request_date_from', '>=', first_day),
                    ('request_date_to', '<=', last_day),
                    ('holiday_status_id', '=', record.holiday_status_id.id),
                ]
                requests_count = self.search_count(domain)
                if requests_count > record.holiday_status_id.requests_limit:
                    raise ValidationError(f"You have reached the maximum number of leave requests ({record.holiday_status_id.requests_limit}) for {record.holiday_status_id.name} in {record.request_date_from.strftime('%B %Y')}.")

    @api.constrains('request_date_from', 'holiday_status_id')
    def _check_request_offset(self):
        is_admin = self.env.user.has_group('base.group_system')
        today = fields.Date.context_today(self)
        requests = self.filtered(lambda r: r.holiday_status_id.enable_request_offset)
        for record in requests:
            limit_date = record.request_date_from - timedelta(days=record.holiday_status_id.request_offset)
            if today > limit_date and not is_admin:
                raise ValidationError(f"The leave request must be at least on or before {limit_date}.")