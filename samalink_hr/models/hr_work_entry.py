import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    def action_adjust_flexible_rest_days(self, date_from, date_to, employee_ids=None):
        """Set work entry types from actual attendance vs flexible rest/absence.

        For employees on flexible schedules:
        - Days classified as actual rest → REST100
        - Days classified as real absence → left unchanged (e.g. OUT from generator)
        - Other working days → attendance (WORK100)
        - Public holidays / approved leave dates → left unchanged
        """
        from_dt = datetime.combine(date_from, time.min)
        to_dt = datetime.combine(date_to, time.max)
        domain = [
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
        ]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids.ids))

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
            real_abs, rest_taken = emp._samalink_flexible_split_absence_and_rest(date_from, date_to)
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
