import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api


_logger = logging.getLogger(__name__)


def _count_weekdays_in_range(date_from, date_to, weekday):
    """Count occurrences of a specific weekday (0=Mon, 6=Sun) in a date range."""
    count = 0
    current = date_from
    while current <= date_to:
        if current.weekday() == weekday:
            count += 1
        current += timedelta(days=1)
    return count


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

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_absent_days(self):
        """Read absent days directly from absence entries.

        Since absence entries now only contain real absences
        (rest days, holidays, time-off, and compensated days are
        filtered out at generation time), we simply count them.
        """
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                payslip.absent_days = 0
                continue
            payslip.absent_days = self.env['hr.absent.entry'].search_count([
                ('employee_id', '=', payslip.employee_id.id),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('leave_entry_id', '=', False),
            ])

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
        """Calculate weekend/rest days based on schedule configuration.

        For flexible schedules:
            rest_days_per_week=1 → count Fridays in the payslip period
            rest_days_per_week=2 → count Fridays + Saturdays

        For non-flexible schedules:
            Use the default REST100 work entry count.
        """
        for payslip in self:
            contract = payslip.contract_id
            calendar = contract.resource_calendar_id if contract else False

            if calendar and calendar.flexible_rest_day:
                rest_per_week = int(calendar.rest_days_per_week or '1')
                count = _count_weekdays_in_range(payslip.date_from, payslip.date_to, 4)  # Fridays
                if rest_per_week == 2:
                    count += _count_weekdays_in_range(payslip.date_from, payslip.date_to, 5)  # Saturdays
                payslip.weekend_days = count
            else:
                from_date_midnight = datetime.combine(payslip.date_from, time.min)
                end_of_to_date = datetime.combine(payslip.date_to, time.max)
                payslip.weekend_days = self.env['hr.work.entry'].search_count([
                    ('employee_id', '=', payslip.employee_id.id),
                    ('date_start', '>=', from_date_midnight),
                    ('date_stop', '<=', end_of_to_date),
                    ('work_entry_type_id.code', '=', 'REST100')
                ])

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
