import logging
from datetime import datetime, time
from odoo import models
from odoo.osv import expression

_logger = logging.getLogger(__name__)

class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    def _compute_related_records_count(self):
        allowed_late_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_late_minutes', default=30)
        allowed_late_hours = int(allowed_late_minutes) / 60.0
        allowed_early_leaving_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_early_leaving_minutes', default=15)
        allowed_early_leaving_hours = int(allowed_early_leaving_minutes) / 60.0
        for line in self:
            if line.salary_rule_id.code != 'LATE_PENALTY':
                super(HrPayslipLine, line)._compute_related_records_count()
            else:
                date_from = line.slip_id.date_from
                date_to = line.slip_id.date_to
                employee_id = line.slip_id.employee_id
                domain = expression.AND([
                    [('employee_id', '=', employee_id.id)],
                    [('check_in', '>=', date_from), ('check_in', '<=', date_to)],
                    ['|', ('late_check_in', '>', allowed_late_hours), ('early_check_out', '>', allowed_early_leaving_hours)],
                ])
                attendance_count = self.env['hr.attendance'].search_count(domain)
                line.update({'related_records_count': attendance_count})

    def open_related_records(self):
        self.ensure_one()
        allowed_late_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_late_minutes', default=30)
        allowed_late_hours = int(allowed_late_minutes) / 60.0
        allowed_early_leaving_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_attendance_deviation.allowed_early_leaving_minutes', default=15)
        allowed_early_leaving_hours = int(allowed_early_leaving_minutes) / 60.0
        if self.salary_rule_id.code != 'LATE_PENALTY':
            return super(HrPayslipLine, self).open_related_records()
        else:
            date_from = self.slip_id.date_from
            date_to = self.slip_id.date_to
            employee_id = self.slip_id.employee_id
            # leave_dates_domain = self._get_leaves_dates_domain()
            action = self.env["ir.actions.actions"]._for_xml_id(
                "samalink_hr.action_hr_attendance_list_payslip"
            )
            action['domain'] = expression.AND([
                [('employee_id', '=', employee_id.id)],
                [('check_in', '>=', date_from), ('check_in', '<=', date_to)],
                ['|', ('late_check_in', '>', allowed_late_hours), ('early_check_out', '>', allowed_early_leaving_hours)],
                # leave_dates_domain
            ])
            return action

    def _get_leaves_dates_domain(self):
        self.ensure_one()
        date_from = self.slip_id.date_from
        date_to = self.slip_id.date_to
        employee_id = self.slip_id.employee_id
        leaves = self.env['hr.leave'].search([
            ('employee_id', '=', employee_id.id),
            ('request_date_from', '>=', date_from),
            ('request_date_to', '<=', date_to),
            ('state', '=', 'validate'),
            ('holiday_status_id.code', '=', 'LATE'),
        ])
        leave_dates_domains = []
        for index, leave_date in enumerate(leaves.mapped('request_date_from')):
            date_midnight = datetime.combine(leave_date, time.min)
            end_of_date = datetime.combine(leave_date, time.max)
            domain = [('check_in', '>=', date_midnight), ('check_in', '<=', end_of_date)]
            leave_dates_domains.append(domain)
        combined_domain = expression.OR(leave_dates_domains)
        _logger.info("Leave dates domain: %s", combined_domain)
        return combined_domain
