from collections import defaultdict
from datetime import date, datetime, time, timedelta
import logging
import requests
import pytz
from urllib.parse import quote
from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

class ZkAttendance(models.Model):
    _name = 'zk.attendance'
    _description = 'ZK Attendance'
    _rec_name = 'emp_code'
    _check_company_auto = True

    zk_id = fields.Char(string='ZK ID', required=True)
    emp_code = fields.Char(string='Employee Code', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', compute='_compute_employee_id', store=True)
    company_id = fields.Many2one('res.company', related='employee_id.company_id', string='Company', store=True)
    dept_code = fields.Char(string='Department Code', required=True)
    department_id = fields.Many2one('zk.department', string='Department', compute='_compute_department_id', store=True)
    att_date = fields.Date(string='Attendance Date', required=True)
    punch_time = fields.Char(string='Punch Time', required=True)
    punch_state = fields.Char(string='Punch State', required=True)
    hr_attendance_id = fields.Many2one('hr.attendance', string='HR Attendance', readonly=True)
    
    @api.depends('emp_code')
    def _compute_employee_id(self):
        employees_codes = self.mapped('emp_code')
        employees = self.env['hr.employee'].search([('pin', 'in', employees_codes)])
        mapped_employees = {emp.pin: emp.id for emp in employees}
        for record in self:
            record.employee_id = mapped_employees.get(record.emp_code, False)

    @api.depends('dept_code')
    def _compute_department_id(self):
        departments = self.env['zk.department'].search([])
        mapped_departments = {dep.dept_code: dep.id for dep in departments}
        for record in self:
            record.department_id = mapped_departments.get(record.dept_code, False)

    @api.model
    def _get_attendance_report(self, headers, api_url, start_date=None, end_date=None, departments=None, employees=None):
        today = date.today()
        yesterday = today - timedelta(days=1)
        start_date = start_date or yesterday.strftime('%Y-%m-%d')
        end_date = end_date or today.strftime('%Y-%m-%d')
        zk_departments = ','.join(str(dep.zk_id) for dep in (departments or self.env['zk.department'].search([])))
        zk_employees = ','.join(str(emp.zk_id) for emp in employees) or '-1'
        endpoint = f"/att/api/transactionReport/?page=1&page_size=200&start_date={start_date}&end_date={end_date}&departments={quote(zk_departments)}&areas=-1&groups=-1&employees={quote(zk_employees)}"
        url = f"{api_url}{endpoint}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses
        json_response = response.json()
        data = json_response.get("data")
        next_page = json_response.get("next")
        while next_page:
            response = requests.get(next_page, headers=headers)
            response.raise_for_status()
            json_response = response.json()
            data.extend(json_response.get("data", []))
            next_page = json_response.get("next")
        return data



    @api.model
    def sync_attendance(self, headers, api_url, start_date=None, end_date=None, departments=None, employees=None):
        """Function to sync attendance from ZK API"""
        try:
            attendance_data = self._get_attendance_report(headers, api_url, start_date, end_date, departments, employees)
        except requests.RequestException as e:
            _logger.error(f"Error fetching attendance data: {e}")
            raise UserError(_("Failed to fetch attendance data from ZK API."))
        existing_records = self.search([]).mapped("zk_id")
        data = []
        for record in attendance_data:
            if str(record["id"]) not in existing_records:
                data.append({
                    'zk_id': record.get('id'),
                    'emp_code': record.get('emp_code'),
                    'dept_code': record.get('dept_code'),
                    'att_date': record.get('att_date'),
                    'punch_time': record.get('punch_time').strip(),
                    'punch_state': record.get('punch_state'),
                })
        
        if data:
            attendance_records = self.create(data)
            _logger.info("Attendance successfully synced from ZK API.")
            return attendance_records

    def action_link_hr_attendance(self):
        _logger.info("Linking ZK attendance records to HR attendance.")
        data = self._get_grouped_data() 
        vals_list = self._format_hr_attendance_data(data)
        self.env['hr.attendance'].create(vals_list)
        _logger.info(f"Created {len(vals_list)} HR attendance records from ZK attendance data.")

    @api.model
    def _format_hr_attendance_data(self, data):
        check_in_out_tolerance_minutes = self.env['ir.config_parameter'].sudo().get_param('hr_zk_api_attendance.check_in_out_tolerance_minutes', default=15)
        vals_list = []
        for employee_id, dates in data.items(): # EX: {1: {'29 Jul 2025': {'check_in': ..., 'check_out': ..., 'ids': [...]}}}
            for att_date_str, punches in dates.items():
                check_in = punches.get('check_in')
                check_out = punches.get('check_out')
                validity = 'valid'
                if abs(check_in - check_out) < timedelta(minutes=check_in_out_tolerance_minutes):
                    validity = 'invalid'
                ids = punches.get('ids', [])
                vals_list.append({
                    'employee_id': employee_id,
                    'check_in': check_in,
                    'check_out': check_out,
                    'zk_attendance_ids': ids,
                    'in_out_validity': validity
                })

        return vals_list

    def _get_grouped_data(self):
        groups = self.env['zk.attendance'].read_group(
            domain=[('id', 'in', self.ids), ('hr_attendance_id', '=', False), ('att_date', '!=', date.today())],
            fields=['employee_id', 'att_date', 'punch_time'],
            groupby=['employee_id', 'att_date:day', 'punch_time', 'id'],
            lazy=False
        )
        data = defaultdict(lambda: defaultdict(lambda: {'check_in': None, 'check_out': None, 'ids': []}))
        for group in groups:
            if not group['employee_id'] or group['att_date:day'] == date.today(): # Skip today's attendance to insure check-in/out validity
                continue
            
            employee_id = group['employee_id'][0]
            att_date_str = group['att_date:day']          # e.g. '29 Jul 2025'
            punch_time_str = group['punch_time'] 

            punch_datetime = self._get_naive_datetime(att_date_str, punch_time_str)

            check_in = data[employee_id][att_date_str].get('check_in')
            check_out = data[employee_id][att_date_str].get('check_out')

            # Set check-in to the earliest bunch
            if not check_in or punch_datetime < check_in:
                check_in = punch_datetime

            # Set check-out to the latest bunch
            if not check_out or punch_datetime > check_out:
                check_out = punch_datetime

            data[employee_id][att_date_str]['check_in'] = check_in
            data[employee_id][att_date_str]['check_out'] = check_out
            data[employee_id][att_date_str]['ids'].append((4, group['id'][0]))
        return data


    @api.model
    def _get_naive_datetime(self, att_date_str, punch_time_str):
        """Convert att_date and punch_time strings to a native datetime object in GMT"""
        cairo_tz = pytz.timezone("Africa/Cairo")
        gmt_tz = pytz.timezone("UTC")
        date_obj = datetime.strptime(att_date_str, "%d %b %Y").date()
        time_obj = datetime.strptime(punch_time_str, "%H:%M").time()
        naive_datetime = datetime.combine(date_obj, time_obj)
        localized_datetime = cairo_tz.localize(naive_datetime)
        gmt_datetime = localized_datetime.astimezone(gmt_tz)
        return gmt_datetime.replace(tzinfo=None)

    def cron_auto_link_hr_attendance(self):
        """Implemented in hr_attendance_deviation module."""
        """Cron job to automatically link HR attendance"""
        pass
        # not_linked = self.search([('hr_attendance_id', '=', False)])
        # if not_linked:
            # not_linked.action_link_hr_attendance()
            # _logger.info(f"Linked {len(not_linked)} ZK attendance records to HR attendance.")
        # else:
            # _logger.info("No ZK attendance records to link to HR attendance.")