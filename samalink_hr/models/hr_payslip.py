from datetime import timedelta

from odoo import models, fields, _


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    # Shown on the payslip form/report in place of the "Reference" (number) field.
    contract_start_date = fields.Date(
        related='contract_id.date_start', string='Contract Start Date', readonly=True)

    def action_compute_sheet(self):
        grouped_payslip_batches = self.grouped('payslip_run_id')
        for batch, payslips in grouped_payslip_batches.items():
            if not batch:
                for payslip in payslips:
                    payslip._samalink_generate_absence_and_adjust_work()
            else:
                payslips._samalink_generate_absence_for_batch(batch)
        return super().action_compute_sheet()

    def _samalink_generate_absence_and_adjust_work(self):
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return
        self.employee_id.action_generate_absent_entries(self.date_from, self.date_to)
        self.env['hr.work.entry'].action_adjust_flexible_rest_days(
            self.date_from, self.date_to, employee_ids=self.employee_id,
        )

    def _samalink_generate_absence_for_batch(self, batch):
        employees = self.mapped('employee_id').filtered(lambda e: e)
        if not employees:
            return
        employees.action_generate_absent_entries(batch.date_start, batch.date_end)
        self.env['hr.work.entry'].action_adjust_flexible_rest_days(
            batch.date_start, batch.date_end, employee_ids=employees,
        )

    def action_samalink_generate_absent_entries(self):
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                continue
            payslip.employee_id.action_generate_absent_entries(
                payslip.date_from, payslip.date_to,
            )
        return self._samalink_notify_done(_('Absence entries have been regenerated for the payslip period.'))

    def action_samalink_adjust_work_entries(self):
        for payslip in self:
            if not payslip.employee_id or not payslip.date_from or not payslip.date_to:
                continue
            self.env['hr.work.entry'].action_adjust_flexible_rest_days(
                payslip.date_from, payslip.date_to, employee_ids=payslip.employee_id,
            )
        return self._samalink_notify_done(_('Flexible work entries have been adjusted for the payslip period.'))

    def _samalink_notify_done(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Done'),
                'type': 'success',
                'message': message,
                'sticky': False,
            },
        }

    def _samalink_get_actual_rest_dates(self):
        """Actual rest days taken (flexible rules) in the payslip period."""
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return []
        contract = self.contract_id
        if not contract or not contract.resource_calendar_id:
            return []
        if not contract.resource_calendar_id.flexible_rest_day:
            return []
        return self.employee_id._samalink_get_actual_rest_dates_flexible(
            self.date_from, self.date_to,
        )

    def _samalink_count_rest_work_entry_days(self):
        """Rest days in payslip period from REST100 work entries (after flexible adjust)."""
        self.ensure_one()
        return self.env['hr.work.entry'].samalink_count_rest_days(
            self.employee_id, self.date_from, self.date_to,
        )
