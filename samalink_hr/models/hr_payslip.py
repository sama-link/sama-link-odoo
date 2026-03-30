from odoo import models

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def compute_sheet(self):
        if hasattr(super(), 'compute_sheet'):
            res = super().compute_sheet()
        else:
            res = True
        self._generate_samalink_absentee_entries()
        return res

    def action_compute_sheet(self):
        if hasattr(super(), 'action_compute_sheet'):
            res = super().action_compute_sheet()
        else:
            res = True
        self._generate_samalink_absentee_entries()
        return res

    def _generate_samalink_absentee_entries(self):
        grouped_payslip_batches = self.grouped('payslip_run_id')
        for batch, payslips in grouped_payslip_batches.items():
            if not batch:
                continue
            payslips.mapped('employee_id').action_generate_absent_entries(batch.date_start, batch.date_end)