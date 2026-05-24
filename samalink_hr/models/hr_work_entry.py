import logging
from datetime import datetime, time, timedelta
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    @api.model
    def samalink_count_rest_days(self, employee, date_from, date_to):
        """Count distinct calendar days with REST100 work entries in the period."""
        if not employee or not date_from or not date_to:
            return 0
        from_dt = datetime.combine(date_from, time.min)
        to_dt = datetime.combine(date_to, time.max)
        entries = self.search([
            ('employee_id', '=', employee.id),
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
            ('work_entry_type_id.code', '=', 'REST100'),
        ])
        return len({entry.date_start.date() for entry in entries})

    def action_adjust_flexible_rest_days(self, date_from, date_to, employee_ids=None):
        """Set work entry types from actual attendance vs flexible rest/absence.

        Only employees whose work schedule has Flexible Rest Days enabled are processed.

        For those employees:
        - Days classified as actual rest → REST100
        - If no rest was taken in a payroll week: default Friday (1 rest/week) or
          Friday + Saturday (2 rest/week) when those days were not attended
        - Days classified as real absence → left unchanged (e.g. OUT from generator)
        - Other working days → attendance (WORK100)
        - Public holidays / approved leave dates → left unchanged
        """
        Employee = self.env['hr.employee']
        if employee_ids is not None:
            employee_ids = Employee._samalink_get_flexible_rest_employees(employee_ids)
            if not employee_ids:
                return
        else:
            employee_ids = Employee._samalink_get_flexible_rest_employees()
            if not employee_ids:
                return

        from_dt = datetime.combine(date_from, time.min)
        to_dt = datetime.combine(date_to, time.max)
        domain = [
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
            ('employee_id', 'in', employee_ids.ids),
        ]

        entries = self.search(domain)
        if not entries:
            return

        attendance_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'WORK100')], limit=1
        )
        rest_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'REST100')], limit=1
        )
        if not attendance_type or not rest_type:
            _logger.warning(
                "WORK100 or REST100 work entry type missing; cannot adjust flexible rest days."
            )
            return

        employees = entries.mapped('employee_id')
        rest_by_emp = {}
        real_by_emp = {}
        holiday_dates = set()
        timeoff_by_emp = {}
        if employees:
            holiday_dates = employees[0]._get_public_holiday_dates(date_from, date_to)
            timeoff_by_emp = employees._get_grouped_timeoff_dates(date_from, date_to)

        for emp in employees:
            cal = emp.contract_id.resource_calendar_id if emp.contract_id else False
            if not cal or not cal.flexible_rest_day:
                continue
            real_abs, rest_taken = emp._samalink_flexible_rest_dates_for_work_entries(
                date_from, date_to,
            )
            rest_by_emp[emp.id] = set(rest_taken)
            real_by_emp[emp.id] = set(real_abs)

        for entry in entries:
            emp = entry.employee_id
            if emp.id not in rest_by_emp:
                continue

            d = entry.date_start.date()
            if d in holiday_dates or d in timeoff_by_emp.get(emp.id, set()):
                continue

            rest_dates = rest_by_emp[emp.id]
            real_dates = real_by_emp[emp.id]

            if d in rest_dates:
                if entry.work_entry_type_id != rest_type:
                    entry.work_entry_type_id = rest_type.id
            elif d in real_dates:
                continue
            else:
                if entry.work_entry_type_id != attendance_type:
                    entry.work_entry_type_id = attendance_type.id

        _logger.info(
            "Adjusted flexible work entries for %d line(s), %d flexible employee(s).",
            len(entries),
            len(rest_by_emp),
        )

    @api.model
    def cron_adjust_flexible_rest_days(self):
        """Scheduled action: adjust work entries for the current week (last 7 days)."""
        today = fields.Date.today()
        date_from = today - timedelta(days=6)
        date_to = today
        self.action_adjust_flexible_rest_days(date_from, date_to)
