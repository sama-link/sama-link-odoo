import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    def action_adjust_flexible_rest_days(self, date_from, date_to, employee_ids=None):
        """Post-process work entries for flexible rest day schedules.

        For employees on flexible schedules (resource.calendar.flexible_rest_day = True):
        - ALL REST100 entries are changed to WORK100 (attendance type)
        - This ensures work entries show all days as working days
        - The actual rest vs absence is determined by hr.absent.entry
        """
        from_dt = datetime.combine(date_from, time.min)
        to_dt = datetime.combine(date_to, time.max)
        domain = [
            ('date_start', '>=', from_dt),
            ('date_stop', '<=', to_dt),
            ('work_entry_type_id.code', '=', 'REST100'),
        ]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids.ids))

        rest_entries = self.search(domain)
        if not rest_entries:
            return

        attendance_type = self.env.ref(
            'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
        )
        if not attendance_type:
            _logger.warning("Work entry type 'attendance' not found, cannot adjust flexible rest days.")
            return

        entries_to_update = self.env['hr.work.entry']
        for entry in rest_entries:
            contract = entry.employee_id.contract_id
            if contract and contract.resource_calendar_id.flexible_rest_day:
                entries_to_update |= entry

        if entries_to_update:
            entries_to_update.write({'work_entry_type_id': attendance_type.id})
            _logger.info(
                "Adjusted %d REST100 work entries to WORK100 for flexible schedules.",
                len(entries_to_update),
            )

    @api.model
    def cron_adjust_flexible_rest_days(self):
        """Scheduled action: adjust work entries for the current week (last 7 days)."""
        today = fields.Date.today()
        date_from = today - timedelta(days=6)
        date_to = today
        self.action_adjust_flexible_rest_days(date_from, date_to)
