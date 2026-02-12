import logging
from collections import defaultdict
from datetime import datetime
from odoo import models, Command, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ZkAttendance(models.Model):
    _inherit = 'zk.attendance'

    is_settled = fields.Boolean(string='Settled', default=False, help='Indicates whether this attendance record has been settled into HR attendance middleware.')

    def _get_grouped_data(self, limit=1):
        groups = self.env['zk.attendance'].read_group(
            domain=[('id', 'in', self.ids), ('employee_id', '!=', False)],
            fields=['employee_id', 'att_date'],
            groupby=['att_date:day', 'employee_id'],
            lazy=False,
            limit=limit
        )
        data = defaultdict(list)
        for group in groups:
            employee_id = group['employee_id'][0]
            att_date = group['att_date:day']  # e.g. '29 Jul 2025'
            date = datetime.strptime(att_date, '%d %b %Y')
            data[date.strftime('%Y-%m-%d')].append(employee_id)
        
        existing_middleware_ids = []
        for att_date, employee_ids in data.items():
            existing_records = self.env['hr.attendance.middleware'].search([
                ('employee_id', 'in', employee_ids),
                ('date', '=', att_date)
            ])
            existing_employee_ids = existing_records.mapped('employee_id').ids
            employee_ids = [eid for eid in employee_ids if eid not in set(existing_employee_ids)]
            data[att_date] = employee_ids
            existing_middleware_ids.extend(existing_records.ids)
        return data, existing_middleware_ids

    def action_link_hr_attendance(self, limit=10):
        data, existing_middleware_ids = self._get_grouped_data(limit=limit)
        _logger.info(f"Linking HR attendance for data: {len(data)}")
        formatted_data = self._format_hr_attendance_data(data)
        created_records = self.env['hr.attendance.middleware'].create(formatted_data)
        _logger.info(f"Created {len(created_records)} HR attendance middleware records.")
        existing_middleware_ids.extend(created_records.ids)
        existing_middleware_records = self.env['hr.attendance.middleware'].browse(existing_middleware_ids)
        _logger.info(f"Processing {len(existing_middleware_records)} existing HR attendance middleware records.")
        # existing_middleware_records.action_fix_work_entries(bulk=True)
        zk_attendance_ids = existing_middleware_records.action_adjust_or_create_hr_attendance(bulk=True)
        self.browse(zk_attendance_ids).write({'is_settled': True})

    @api.model
    def _format_hr_attendance_data(self, data):
        vals_list = []
        for att_date, employee_ids in data.items(): # EX: {'29 Jul 2025': [1, 2, 3]}
            for employee_id in employee_ids:
                vals_list.append({
                    'employee_id': employee_id,
                    'date': att_date,
                })

        return vals_list

    def cron_auto_link_hr_attendance(self, limit=30, start_date='2025-10-24'):
        _logger.info("Starting cron job to link ZK attendance records to HR attendance middleware.")
        records = self.search([('is_settled', '=', False), ('att_date', '>=', start_date)], order='att_date asc')
        _logger.info(f"Found {len(records)} ZK attendance records to process.")
        if records:
            records.action_link_hr_attendance(limit=limit)
            _logger.info(f"Cron job completed: Linked {len(records)} ZK attendance records to HR attendance middleware.")
        else:
            _logger.info("Cron job completed: No ZK attendance records to link.")