from collections import defaultdict
from datetime import datetime, time, timedelta
from odoo import models

class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    def _get_friday_week_key(self, day):
        """Return the anchor Friday date for a Friday->Thursday payroll week."""
        offset = (day.weekday() - 4) % 7
        return day - timedelta(days=offset)

    def _get_excluded_schedule_names(self):
        """Option A: exclude listed schedules from Friday swap logic."""
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

    def _get_slip_schedule_name(self, slip):
        contract = slip.contract_id
        if not contract and slip.employee_id:
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', slip.employee_id.id),
                ('state', '=', 'open'),
                ('date_start', '<=', slip.date_to),
                '|',
                ('date_end', '=', False),
                ('date_end', '>=', slip.date_from),
            ], limit=1)
        return (contract.resource_calendar_id.name or '').strip() if contract else ''

    def _is_friday_swap_in_scope(self, slip):
        excluded_ids = self._get_excluded_schedule_ids()
        schedule_id = slip.contract_id.resource_calendar_id.id if slip.contract_id else False
        if excluded_ids and schedule_id:
            return schedule_id not in excluded_ids
        return self._get_slip_schedule_name(slip) not in self._get_excluded_schedule_names()

    def _get_weekly_friday_attendance_credits(self, employee, date_from, date_to):
        attendance_dates = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', date_from),
            ('check_in', '<=', date_to),
        ]).mapped('check_in')
        credits = defaultdict(int)
        for check_in in attendance_dates:
            check_day = check_in.date()
            if check_day.weekday() == 4:  # Friday
                credits[self._get_friday_week_key(check_day)] += 1
        return credits

    def _get_approved_timeoff_dates(self, employee, date_from, date_to):
        from_date_midnight = datetime.combine(date_from, time.min)
        end_of_to_date = datetime.combine(date_to, time.max)
        approved_leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', end_of_to_date),
            ('date_to', '>=', from_date_midnight),
        ])
        timeoff_dates = set()
        for leave in approved_leaves:
            start_day = max(leave.date_from.date(), date_from)
            end_day = min(leave.date_to.date(), date_to)
            cursor_date = start_day
            while cursor_date <= end_day:
                timeoff_dates.add(cursor_date)
                cursor_date += timedelta(days=1)
        return timeoff_dates

    def _get_compensation_stats(self, slip, absent_entries=None):
        employee = slip.employee_id
        date_from = slip.date_from
        date_to = slip.date_to
        absent_entries = absent_entries if absent_entries is not None else self.env['hr.absent.entry'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('leave_entry_id', '=', False),
        ])
        if not absent_entries:
            return 0, set()

        approved_timeoff_dates = self._get_approved_timeoff_dates(employee, date_from, date_to)
        friday_credits = self._get_weekly_friday_attendance_credits(employee, date_from, date_to)
        compensated_absences = 0
        compensated_weeks = set()
        for absent_entry in absent_entries.sorted('date'):
            if absent_entry.date.weekday() == 4 or absent_entry.date in approved_timeoff_dates:
                continue
            week_key = self._get_friday_week_key(absent_entry.date)
            if friday_credits.get(week_key, 0) > 0:
                friday_credits[week_key] -= 1
                compensated_absences += 1
                compensated_weeks.add(week_key)
        return compensated_absences, compensated_weeks

    def _compute_adjusted_absent_penalty_count(self, slip):
        employee = slip.employee_id
        date_from = slip.date_from
        date_to = slip.date_to
        absent_entries = self.env['hr.absent.entry'].search([
            ('employee_id', '=', employee.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('leave_entry_id', '=', False),
        ])
        if not absent_entries:
            return 0
        if not self._is_friday_swap_in_scope(slip):
            return len(absent_entries)

        compensated_absences, _ = self._get_compensation_stats(slip, absent_entries=absent_entries)
        return len(absent_entries) - compensated_absences

    def _compute_adjusted_rest_allow_count(self, slip):
        employee = slip.employee_id
        from_date_midnight = datetime.combine(slip.date_from, time.min)
        end_of_to_date = datetime.combine(slip.date_to, time.max)
        rest_entries = self.env['hr.work.entry'].search([
            ('employee_id', '=', employee.id),
            ('date_start', '>=', from_date_midnight),
            ('date_stop', '<=', end_of_to_date),
            ('work_entry_type_id.code', '=', 'REST100')
        ])
        if not rest_entries or not self._is_friday_swap_in_scope(slip):
            return len(rest_entries)
        _, compensated_weeks = self._get_compensation_stats(slip)
        if not compensated_weeks:
            return len(rest_entries)

        attendance_dates = {
            check_in.date() for check_in in self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', from_date_midnight),
                ('check_in', '<=', end_of_to_date),
            ]).mapped('check_in')
        }
        friday_rest_with_attendance = sum(
            1
            for rest_entry in rest_entries
            if (
                rest_entry.date_start.date().weekday() == 4
                and rest_entry.date_start.date() in attendance_dates
                and self._get_friday_week_key(rest_entry.date_start.date()) in compensated_weeks
            )
        )
        return max(len(rest_entries) - friday_rest_with_attendance, 0)

    def _compute_related_records_count(self):
        for line in self:
            date_from = line.slip_id.date_from
            date_to = line.slip_id.date_to
            employee_id = line.slip_id.employee_id
            if line.salary_rule_id.code not in ['PRESENT_DAYS', 'REST_ALLOW', 'ABSENT_PENALTY']:
                super(HrPayslipLine, line)._compute_related_records_count()
            elif line.salary_rule_id.code == 'PRESENT_DAYS':
                attendance_count = self.env['hr.attendance'].search_count(
                    [('check_in', '>=', date_from), ('check_in', '<=', date_to),
                     ('employee_id', '=', employee_id.id)]
                )
                line.update({'related_records_count': attendance_count})
            elif line.salary_rule_id.code == 'REST_ALLOW':
                weekend_days = line._compute_adjusted_rest_allow_count(line.slip_id)
                line.update({'related_records_count': weekend_days})
            elif line.salary_rule_id.code == 'ABSENT_PENALTY':
                absent_entries_count = line._compute_adjusted_absent_penalty_count(line.slip_id)
                line.update({'related_records_count': absent_entries_count})

    def open_related_records(self):
        self.ensure_one()
        date_from = self.slip_id.date_from
        date_to = self.slip_id.date_to
        employee_id = self.slip_id.employee_id
        if self.salary_rule_id.code not in ['PRESENT_DAYS', 'REST_ALLOW', 'ABSENT_PENALTY']:
            return super(HrPayslipLine, self).open_related_records()
        elif self.salary_rule_id.code == 'PRESENT_DAYS':
            action = self.env["ir.actions.actions"]._for_xml_id(
                "samalink_hr.action_hr_attendance_list_payslip"
            )
            action['domain'] = [
                ('check_in', '>=', date_from), ('check_in', '<=', date_to),
                ('employee_id', '=', employee_id.id)
            ]
            return action
        elif self.salary_rule_id.code == 'REST_ALLOW':
            from_date_midnight = datetime.combine(date_from, time.min)
            end_of_to_date = datetime.combine(date_to, time.max)
            action = self.env["ir.actions.actions"]._for_xml_id(
                "samalink_hr.action_hr_rest_allow_list_payslip"
            )
            action['domain'] = [
                ('employee_id', '=', employee_id.id),
                ('date_start', '>=', from_date_midnight),
                ('date_stop', '<=', end_of_to_date),
                ('work_entry_type_id.code', '=', 'REST100')
            ]
            return action
        elif self.salary_rule_id.code == 'ABSENT_PENALTY':
            action = self.env.ref('samalink_hr.action_hr_absent_entry').read()[0]
            action['domain'] = [
                ('employee_id', '=', employee_id.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('leave_entry_id', '=', False)
            ]
            action['context'] = {'default_employee_id': employee_id.id, 'initial_date': date_from}
            return action