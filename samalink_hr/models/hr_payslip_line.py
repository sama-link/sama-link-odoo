from datetime import datetime, time
from odoo import models, _


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
        """Rest-day count for REST_ALLOW: REST100 work entries in the payslip period.

        Flexible and non-flexible schedules both use work entries marked REST100
        (set by ``action_adjust_flexible_rest_days`` for flexible employees).
        """
        return slip._samalink_count_rest_work_entry_days()

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