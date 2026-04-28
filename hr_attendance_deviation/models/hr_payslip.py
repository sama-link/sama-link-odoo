import logging
from collections import defaultdict
from datetime import datetime, time
from odoo import models, fields, api


_logger = logging.getLogger(__name__)

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    late_days = fields.Float(
        string='Late Days',
        compute='_compute_partial_shift_days_hours',
        help='Total days of late attendance for the payslip period.',
    )
    late_hours = fields.Float(
        string='Late Hours',
        compute='_compute_partial_shift_days_hours',
        help='Total hours of late attendance for the payslip period.',
    )
    late_permission_count = fields.Integer(
        string='Late/Early Leaving Permissions',
        compute='_compute_late_permission',
        help='Number of late permissions granted during the payslip period.',
    )
    late_permission_hours = fields.Float(
        string='Late/Early Leaving Permission Hours',
        compute='_compute_late_permission',
        help='Total hours of late permissions granted during the payslip period.',
    )
    early_leaving_days = fields.Float(
        string='Early Leaving Days',
        compute='_compute_partial_shift_days_hours',
        help='Total days of early leaving for the payslip period.',
    )
    early_leaving_hours = fields.Float(
        string='Early Leaving Hours',
        compute='_compute_partial_shift_days_hours',
        help='Total hours of early leaving for the payslip period.',
    )
    overtime_hours = fields.Float(
        string='Overtime Hours (Approved)',
        compute='_compute_overtime_hours',
        help='Total overtime hours for the payslip period.',
    )
    days_attended = fields.Float(
        string='Days Attended',
        compute='_compute_days_attended',
        help='Total days of attendance for the payslip period.',
    )
    weekend_days = fields.Float(
        string='Weekend Off Days',
        compute='_compute_weekend_days',
        help='Total weekend days for the payslip period.',
    )
    timeoff_days = fields.Float(
        string='Time Off Days',
        compute='_compute_timeoff_days',
        help='Total time off days for the payslip period.',
    )
    absent_days = fields.Float(
        string='Absent Days',
        compute='_compute_absent_days',
        help='Total absent days for the payslip period.',   
    )
    generic_timeoff_days = fields.Float(
        string='Generic Time Off',
        compute='_compute_timeoff_days',
    )
    unpaid_leaves = fields.Float(
        string='Unpaid Leaves',
        compute='_compute_timeoff_days',
    )
    sick_timeoff_days = fields.Float(
        string='Sick Time Off',
        compute='_compute_timeoff_days',
    )
    paid_timeoff_days = fields.Float(
        string='Paid Time Off',
        compute='_compute_timeoff_days',
    )
    casual_timeoff_days = fields.Float(
        string='Casual Time Off',
        compute='_compute_timeoff_days',
    )

    def _get_excluded_schedule_names(self):
        default_value = 'شيفت اداريين الفروع,شيفت الادارة'
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'samalink_hr.friday_swap_excluded_schedule_names',
            default=default_value,
        )
        return {name.strip() for name in (raw_value or '').split(',') if name.strip()}

    def _get_excluded_schedule_ids(self):
        raw_value = self.env['ir.config_parameter'].sudo().get_param(
            'samalink_hr.friday_swap_excluded_schedule_ids',
            default='',
        )
        schedule_ids = set()
        for value in (raw_value or '').split(','):
            value = value.strip()
            if value.isdigit():
                schedule_ids.add(int(value))
        return schedule_ids

    def _is_friday_swap_in_scope(self):
        self.ensure_one()
        schedule = self.contract_id.resource_calendar_id
        excluded_ids = self._get_excluded_schedule_ids()
        if excluded_ids and schedule:
            return schedule.id not in excluded_ids
        schedule_name = (schedule.name or '').strip()
        return schedule_name not in self._get_excluded_schedule_names()

    def _get_weekly_friday_attendance_credits(self):
        self.ensure_one()
        attendance_dates = self.env['hr.attendance'].search([
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '>=', self.date_from),
            ('check_in', '<=', self.date_to),
        ]).mapped('check_in')
        credits = defaultdict(int)
        for check_in in attendance_dates:
            check_day = check_in.date()
            if check_day.weekday() == 4:
                iso_year, iso_week, _ = check_day.isocalendar()
                credits[(iso_year, iso_week)] += 1
        return credits

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_absent_days(self):
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                payslip.absent_days = 0
                continue
            absent_entries = self.env['hr.absent.entry'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('leave_entry_id', '=', False),
            ])
            if not absent_entries or not payslip._is_friday_swap_in_scope():
                payslip.absent_days = len(absent_entries)
                continue

            friday_credits = payslip._get_weekly_friday_attendance_credits()
            compensated_absences = 0
            for absent_entry in absent_entries.sorted('date'):
                if absent_entry.date.weekday() == 4:
                    continue
                iso_year, iso_week, _ = absent_entry.date.isocalendar()
                week_key = (iso_year, iso_week)
                if friday_credits.get(week_key, 0) > 0:
                    friday_credits[week_key] -= 1
                    compensated_absences += 1
            payslip.absent_days = len(absent_entries) - compensated_absences

    def _compute_timeoff_days(self):
        attendance_type = self.env.ref('hr_work_entry.work_entry_type_attendance')
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            timeoff_entries = self.env['hr.work.entry'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_start', '>=', from_date_midnight),
                ('date_stop', '<=', end_of_to_date),
                ('work_entry_type_id', '!=', attendance_type.id),
                ('work_entry_type_id.code', 'not in', ['LATE', 'REST100'])
            ])
            payslip.timeoff_days = len(timeoff_entries)
            payslip.generic_timeoff_days = len(timeoff_entries.filtered(lambda entry: entry.work_entry_type_id.code == 'LEAVE100'))
            payslip.unpaid_leaves = len(timeoff_entries.filtered(lambda entry: entry.work_entry_type_id.code == 'LEAVE90'))
            payslip.sick_timeoff_days = len(timeoff_entries.filtered(lambda entry: entry.work_entry_type_id.code == 'LEAVE110'))
            payslip.paid_timeoff_days = len(timeoff_entries.filtered(lambda entry: entry.work_entry_type_id.code == 'LEAVE120'))
            payslip.casual_timeoff_days = len(timeoff_entries.filtered(lambda entry: entry.work_entry_type_id.code == 'CAS100'))

    def _compute_overtime_hours(self):
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            overtime_attendances = self.env['hr.attendance'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('check_in', '>=', from_date_midnight),
                ('check_in', '<=', end_of_to_date),
                ('overtime_status', '=', 'approved')
            ])
            payslip.overtime_hours = sum(overtime_attendances.mapped('validated_overtime_hours'))

    def _compute_late_permission(self):
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            late_permissions = self.env['hr.work.entry'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_start', '>=', from_date_midnight),
                ('date_stop', '<=', end_of_to_date),
                ('work_entry_type_id.code', '=', 'LATE')
            ])
            payslip.late_permission_count = len(late_permissions)
            payslip.late_permission_hours = sum(late_permissions.mapped('duration'))

    def _compute_weekend_days(self):
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            rest_entries = self.env['hr.work.entry'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('date_start', '>=', from_date_midnight),
                ('date_stop', '<=', end_of_to_date),
                ('work_entry_type_id.code', '=', 'REST100')
            ])
            if not rest_entries or not payslip._is_friday_swap_in_scope():
                payslip.weekend_days = len(rest_entries)
                continue

            attendance_dates = {
                check_in.date() for check_in in self.env['hr.attendance'].search([
                    ('employee_id', '=', payslip.employee_id.id),
                    ('check_in', '>=', from_date_midnight),
                    ('check_in', '<=', end_of_to_date),
                ]).mapped('check_in')
            }
            friday_rest_with_attendance = sum(
                1
                for rest_entry in rest_entries
                if rest_entry.date_start.date().weekday() == 4 and rest_entry.date_start.date() in attendance_dates
            )
            payslip.weekend_days = max(len(rest_entries) - friday_rest_with_attendance, 0)

    def _compute_days_attended(self):
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            days_attended = self.env['hr.attendance'].search_count([
                ('employee_id', '=', payslip.employee_id.id),
                ('check_in', '>=', from_date_midnight),
                ('check_in', '<=', end_of_to_date)
            ])
            payslip.days_attended = days_attended

    def _compute_partial_shift_days_hours(self):
        for payslip in self:
            from_date_midnight = datetime.combine(payslip.date_from, time.min)
            end_of_to_date = datetime.combine(payslip.date_to, time.max)
            attendances = self.env['hr.attendance'].search([
                ('employee_id', '=', payslip.employee_id.id),
                ('check_in', '>=', from_date_midnight),
                ('check_in', '<=', end_of_to_date)
            ])
            late_days_hours = attendances.filtered('late_check_in_approved').get_late_days_hours()
            payslip.late_days = late_days_hours['late_days']
            payslip.late_hours = late_days_hours['late_hours']
            early_leaving_days_hours = attendances.filtered('early_check_out_approved').get_early_leaving_days_hours()
            payslip.early_leaving_days = early_leaving_days_hours['early_leaving_days']
            payslip.early_leaving_hours = early_leaving_days_hours['early_leaving_hours']
