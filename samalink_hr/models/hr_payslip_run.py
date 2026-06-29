from odoo import models, _


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def action_samalink_generate_absent_entries(self):
        """Bulk: regenerate absence entries for every payslip in the batch.
        Delegates to the per-payslip action, which uses each payslip's own period."""
        self.ensure_one()
        if not self.slip_ids:
            return self._samalink_notify_no_slips()
        return self.slip_ids.action_samalink_generate_absent_entries()

    def action_samalink_adjust_work_entries(self):
        """Bulk: adjust flexible work entries for every payslip in the batch."""
        self.ensure_one()
        if not self.slip_ids:
            return self._samalink_notify_no_slips()
        return self.slip_ids.action_samalink_adjust_work_entries()

    def _samalink_notify_no_slips(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('No Payslips'),
                'type': 'warning',
                'message': _('This batch has no payslips to process.'),
                'sticky': False,
            },
        }
