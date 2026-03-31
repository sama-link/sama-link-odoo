from odoo import models

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def action_compute_sheet(self):
        grouped_payslip_batches = self.grouped('payslip_run_id')
        for batch, payslips in grouped_payslip_batches.items():
            if not batch:
                for payslip in payslips:
                    payslip.employee_id.action_generate_absent_entries(payslip.date_from, payslip.date_to)
                continue
            payslips.mapped('employee_id').action_generate_absent_entries(batch.date_start, batch.date_end)
        res = super().action_compute_sheet()
        return res