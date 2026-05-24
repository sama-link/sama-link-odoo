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
        - If rest < entitlement in a payroll week: default Friday (1 rest/week) or
          Friday + Saturday (2 rest/week); if the employee also worked that day,
          keep the attendance/work entry and add a separate REST100 line
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
            _logger.info(
                "Flex adjust: no work entries for %d employee(s) in %s – %s",
                len(employee_ids), date_from, date_to,
            )
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

        has_leave_id = 'leave_id' in self._fields

        employees = entries.mapped('employee_id')
        rest_by_emp = {}
        real_by_emp = {}
        attendance_by_emp = {}
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
            attendance_by_emp[emp.id] = set(
                emp._get_grouped_attendance_dates(date_from, date_to).get(emp.id, [])
            )
            _logger.info(
                "Flex adjust emp %s [%s]: rest=%s, abs=%s, attended=%s",
                emp.id, emp.name,
                sorted(rest_by_emp[emp.id]),
                sorted(real_by_emp[emp.id]),
                sorted(attendance_by_emp[emp.id]),
            )

        created_rest = 0
        converted_rest = 0

        for emp in employees:
            if emp.id not in rest_by_emp:
                continue
            emp_entries = entries.filtered(lambda e: e.employee_id == emp)
            rest_dates = rest_by_emp[emp.id]
            real_dates = real_by_emp[emp.id]
            attended_dates = attendance_by_emp.get(emp.id, set())

            for d in sorted(rest_dates):
                if d in holiday_dates or d in timeoff_by_emp.get(emp.id, set()):
                    _logger.debug(
                        "Flex: emp %s day %s → skip (holiday/leave)", emp.id, d,
                    )
                    continue

                day_entries = emp_entries.filtered(
                    lambda e, day=d: e.date_start and e.date_start.date() == day
                )
                has_check_in = d in attended_dates

                if not day_entries:
                    _logger.warning(
                        "Flex: emp %s day %s → no work entries (check_in=%s); "
                        "run 'Regenerate Work Entries' first.",
                        emp.id, d, has_check_in,
                    )
                    continue

                non_leave = day_entries.filtered(
                    lambda e: not (has_leave_id and e.leave_id)
                )
                work_entries = non_leave.filtered(
                    lambda e: e.work_entry_type_id != rest_type
                )

                if has_check_in and work_entries:
                    already_rest = day_entries.filtered(
                        lambda e: e.work_entry_type_id == rest_type
                    )
                    if not already_rest:
                        self._samalink_create_rest_work_entry(
                            work_entries[0], rest_type,
                        )
                        created_rest += 1
                        _logger.info(
                            "Flex: emp %s day %s → DUAL created REST100 "
                            "alongside %s (%s)",
                            emp.id, d,
                            work_entries[0].work_entry_type_id.code,
                            work_entries[0].work_entry_type_id.name,
                        )
                    continue

                for entry in non_leave:
                    if d in real_dates:
                        continue
                    if entry.work_entry_type_id != rest_type:
                        _logger.info(
                            "Flex: emp %s day %s → convert %s → REST100",
                            emp.id, d, entry.work_entry_type_id.code,
                        )
                        entry.work_entry_type_id = rest_type.id
                        converted_rest += 1

        for entry in entries:
            emp = entry.employee_id
            if emp.id not in rest_by_emp:
                continue
            if has_leave_id and entry.leave_id:
                continue

            d = entry.date_start.date()
            if d in holiday_dates or d in timeoff_by_emp.get(emp.id, set()):
                continue

            rest_dates = rest_by_emp[emp.id]
            real_dates = real_by_emp[emp.id]

            if d in rest_dates:
                if d in attendance_by_emp.get(emp.id, set()):
                    if entry.work_entry_type_id != rest_type:
                        continue
                if entry.work_entry_type_id == rest_type:
                    continue
                if d in real_dates:
                    continue
                entry.work_entry_type_id = rest_type.id
            elif d in real_dates:
                continue
            else:
                if entry.work_entry_type_id != attendance_type:
                    entry.work_entry_type_id = attendance_type.id

        _logger.info(
            "Flex adjust done: %d entries, %d flex employees, "
            "created %d dual REST100, converted %d to REST100.",
            len(entries), len(rest_by_emp), created_rest, converted_rest,
        )

    @api.model
    def _samalink_is_leave_work_entry(self, entry):
        """True when the entry was generated from an approved leave."""
        if 'leave_id' in self._fields and entry.leave_id:
            return True
        return False

    @api.model
    def _samalink_create_rest_work_entry(self, template_entry, rest_type):
        """Add a REST100 line alongside an existing attendance/work entry (same slot)."""
        emp = template_entry.employee_id
        day = template_entry.date_start.date()
        from_dt = datetime.combine(day, time.min)
        to_dt = datetime.combine(day, time.max)
        existing = self.search([
            ('employee_id', '=', emp.id),
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
            ('work_entry_type_id', '=', rest_type.id),
        ], limit=1)
        if existing:
            return existing
        vals = {
            'name': rest_type.name or _('Rest Day'),
            'employee_id': emp.id,
            'date_start': template_entry.date_start,
            'date_stop': template_entry.date_stop,
            'work_entry_type_id': rest_type.id,
            'company_id': template_entry.company_id.id,
        }
        if 'duration' in self._fields and template_entry.duration:
            vals['duration'] = template_entry.duration
        if 'contract_id' in self._fields and template_entry.contract_id:
            vals['contract_id'] = template_entry.contract_id.id
        return self.create(vals)

    @api.model
    def cron_adjust_flexible_rest_days(self):
        """Scheduled action: adjust work entries for the current week (last 7 days)."""
        today = fields.Date.today()
        date_from = today - timedelta(days=6)
        date_to = today
        self.action_adjust_flexible_rest_days(date_from, date_to)
