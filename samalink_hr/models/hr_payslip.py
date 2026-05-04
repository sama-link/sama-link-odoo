from odoo import models

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_compute_sheet(self):
        grouped_payslip_batches = self.grouped('payslip_run_id')
        for batch, payslips in grouped_payslip_batches.items():
            if not batch:
                for payslip in payslips:
                    payslip.employee_id.action_generate_absent_entries(payslip.date_from, payslip.date_to)
                    self.env['hr.work.entry'].action_adjust_flexible_rest_days(
                        payslip.date_from, payslip.date_to, employee_ids=payslip.employee_id,
                    )
                continue
            payslips.mapped('employee_id').action_generate_absent_entries(batch.date_start, batch.date_end)
            self.env['hr.work.entry'].action_adjust_flexible_rest_days(
                batch.date_start, batch.date_end, employee_ids=payslips.mapped('employee_id'),
            )
        res = super().action_compute_sheet()
        return res