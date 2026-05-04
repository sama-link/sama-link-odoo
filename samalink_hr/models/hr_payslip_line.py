from datetime import datetime, time, timedelta
from odoo import models, _


def _count_weekdays_in_range(date_from, date_to, weekday):
    """Count occurrences of a specific weekday (0=Mon, 6=Sun) in a date range."""
    count = 0
    current = date_from
    while current <= date_to:
        if current.weekday() == weekday:
            count += 1
        current += timedelta(days=1)
    return count


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    def _compute_adjusted_absent_penalty_count(self, slip):
        """Read penalty count directly from absence entries.

        Since absence entries now only contain real absences
        (rest days, holidays, time-off, and compensated days are
        filtered out at generation time), we simply count all entries.
        """
        return self.env['hr.absent.entry'].search_count([
            ('employee_id', '=', slip.employee_id.id),
            ('date', '>=', slip.date_from),
            ('date', '<=', slip.date_to),
        ])

    def _compute_adjusted_rest_allow_count(self, slip):
        """Calculate rest-day count for payroll expressions / related count.

        For flexible schedules: same **calendar** rule as before — count Fridays
        in the payslip period, plus Saturdays when ``rest_days_per_week`` is 2
        (schedule entitlement in the period), **not** the number of rest days
        actually taken.

        For non-flexible schedules: count REST100 work entries in the period.
        """
        contract = slip.contract_id
        calendar = contract.resource_calendar_id if contract else False

        if calendar and calendar.flexible_rest_day:
            rest_per_week = int(calendar.rest_days_per_week or '1')
            count = _count_weekdays_in_range(slip.date_from, slip.date_to, 4)  # Fridays
            if rest_per_week == 2:
                count += _count_weekdays_in_range(slip.date_from, slip.date_to, 5)  # Saturdays
            return count

        # Non-flexible: use default REST100 work entries
        from_dt = datetime.combine(slip.date_from, time.min)
        to_dt = datetime.combine(slip.date_to, time.max)
        return self.env['hr.work.entry'].search_count([
            ('employee_id', '=', slip.employee_id.id),
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
            ('work_entry_type_id.code', '=', 'REST100'),
        ])

    def _is_flexible_schedule(self, slip):
        """Check if the employee's schedule uses flexible rest days."""
        contract = slip.contract_id
        calendar = contract.resource_calendar_id if contract else False
        return calendar and calendar.flexible_rest_day

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
            if self._is_flexible_schedule(self.slip_id):
                # Drill-down: actual rest days taken (not the calendar Fri/Sat count).
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Rest days taken'),
                    'res_model': 'hr.payslip.rest.days.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_payslip_id': self.slip_id.id},
                }
            from_date_midnight = datetime.combine(date_from, time.min)
            end_of_to_date = datetime.combine(date_to, time.max)
            action = self.env["ir.actions.actions"]._for_xml_id(
                "samalink_hr.action_hr_rest_allow_list_payslip"
            )
            action['domain'] = [
                ('employee_id', '=', employee_id.id),
                ('date_start', '>=', from_date_midnight),
                ('date_stop', '<=', end_of_to_date),
                ('work_entry_type_id.code', '=', 'REST100'),
            ]
            return action
        elif self.salary_rule_id.code == 'ABSENT_PENALTY':
            action = self.env.ref('samalink_hr.action_hr_absent_entry').read()[0]
            action['domain'] = [
                ('employee_id', '=', employee_id.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ]
            action['context'] = {'default_employee_id': employee_id.id, 'initial_date': date_from}
            return action