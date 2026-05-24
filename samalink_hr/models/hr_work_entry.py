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

        attendance_wetype = self.env.ref(
            'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
        )

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

        created_rest = 0
        for emp in employees:
            if emp.id not in rest_by_emp:
                continue
            emp_entries = entries.filtered(lambda e: e.employee_id == emp)
            rest_dates = rest_by_emp[emp.id]
            real_dates = real_by_emp[emp.id]
            attended_dates = attendance_by_emp.get(emp.id, set())

            for d in sorted(rest_dates):
                if d in holiday_dates or d in timeoff_by_emp.get(emp.id, set()):
                    continue
                day_entries = emp_entries.filtered(
                    lambda e, day=d: e.date_start and e.date_start.date() == day
                )
                if not day_entries:
                    continue

                work_entries = day_entries.filtered(
                    lambda e: self._samalink_is_work_attendance_entry(
                        e, attendance_type, attendance_wetype, rest_type,
                    )
                )
                has_check_in = d in attended_dates

                if has_check_in and work_entries:
                    if not day_entries.filtered(lambda e: e.work_entry_type_id == rest_type):
                        self._samalink_create_rest_work_entry(work_entries[0], rest_type)
                        created_rest += 1
                    continue

                for entry in day_entries:
                    if d in real_dates:
                        continue
                    if entry.work_entry_type_id != rest_type:
                        entry.work_entry_type_id = rest_type.id

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
                if d in attendance_by_emp.get(emp.id, set()) and self._samalink_is_work_attendance_entry(
                    entry, attendance_type, attendance_wetype, rest_type,
                ):
                    continue
                if entry.work_entry_type_id == rest_type:
                    continue
                if d in real_dates:
                    continue
                if entry.work_entry_type_id != rest_type:
                    entry.work_entry_type_id = rest_type.id
            elif d in real_dates:
                continue
            else:
                if entry.work_entry_type_id != attendance_type:
                    entry.work_entry_type_id = attendance_type.id

        _logger.info(
            "Adjusted flexible work entries for %d line(s), %d flexible employee(s), "
            "created %d extra REST100 line(s) for worked rest days.",
            len(entries),
            len(rest_by_emp),
            created_rest,
        )

    @api.model
    def _samalink_is_work_attendance_entry(
        self, entry, attendance_type, attendance_wetype, rest_type,
    ):
        """True for lines that represent worked time (kept when adding REST100 on same day)."""
        wet = entry.work_entry_type_id
        if not wet or wet == rest_type:
            return False
        if wet == attendance_type:
            return True
        if attendance_wetype and wet == attendance_wetype:
            return True
        code = (wet.code or '').upper()
        if code in ('WORK100', 'ATTENDANCE') or code.startswith('WORK'):
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
