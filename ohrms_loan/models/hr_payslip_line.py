from odoo import models

class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    def _compute_related_records_count(self):
        for line in self:
            if line.salary_rule_id.code != 'ADVANCE':
                super(HrPayslipLine, line)._compute_related_records_count()
            else:
                date_from = line.slip_id.date_from
                date_to = line.slip_id.date_to
                employee_id = line.slip_id.employee_id
                loan_lines_count = self.env['hr.loan.line'].search_count(
                    [('date', '>=', date_from), ('date', '<=', date_to),
                     ('loan_id.employee_id', '=', employee_id.id),
                     ('loan_id.state', '=', 'approve')]
                )
                line.update({'related_records_count': loan_lines_count})

    def open_related_records(self):
        self.ensure_one()
        if self.salary_rule_id.code != 'ADVANCE':
            return super(HrPayslipLine, self).open_related_records()
        else:
            date_from = self.slip_id.date_from
            date_to = self.slip_id.date_to
            employee_id = self.slip_id.employee_id
            action = self.env["ir.actions.actions"]._for_xml_id(
                "ohrms_loan.hr_loan_line_action_payslip"
            )
            action['domain'] = [
                ('date', '>=', date_from), ('date', '<=', date_to),
                ('loan_id.employee_id', '=', employee_id.id),
                ('loan_id.state', '=', 'approve')
            ]
            return action