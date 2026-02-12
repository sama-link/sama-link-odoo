import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ZkEmployee(models.Model):
    _name = 'zk.employee'
    _description = 'ZK Employee'
    _rec_name = 'full_name'
    _rec_names_search = ['full_name', 'emp_code', 'zk_id', 'employee_id']

    zk_id = fields.Char(string='Employee ID', required=True)
    emp_code = fields.Char(string='Employee Code', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', compute='_compute_employee_id', store=True)
    full_name = fields.Char(string='Full Name', required=True)
    dept_code = fields.Char(string='Department Code', required=True)
    department_id = fields.Many2one('zk.department', string='Department', compute='_compute_department_id', store=True)
    hire_date = fields.Date(string='Hire Date', required=True)

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
    def _get_employees_data(self, headers, api_url):
        endpoint = "/personnel/api/employees/"
        url = f"{api_url}{endpoint}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        json_response = response.json()
        data = json_response.get("data", [])
        next_page = json_response.get("next")
        while next_page:
            response = requests.get(next_page, headers=headers)
            response.raise_for_status()
            json_response = response.json()
            data.extend(json_response.get("data", []))
            next_page = json_response.get("next")
        return data

    @api.model
    def sync_employees(self, headers, api_url):
        try:
            employees_data = self._get_employees_data(headers, api_url)
        except requests.exceptions.HTTPError as e:
            _logger.error(f"Error fetching employees: {e}")
            raise UserError(_("Failed to fetch employees from ZK API."))
        
        if not employees_data:
            _logger.warning("No employees found in ZK API response.")
            return

        existing_employees = self.search([]).mapped("zk_id")
        vals_list = []
        for employee in employees_data:
            if str(employee["id"]) not in existing_employees:
                vals_list.append({
                    "zk_id": employee["id"],
                    "emp_code": employee["emp_code"],
                    "full_name": employee["full_name"],
                    "dept_code": employee['department']["dept_code"],
                    "hire_date": employee["hire_date"],
                })
        if vals_list:
            self.create(vals_list)
        _logger.info("Employees successfully synced from ZK API.")

    def __create_hr_employees(self):
        not_linked = self.filtered(lambda r: not r.employee_id)
        existing_employees = self.env['hr.employee'].search([('pin', 'in', not_linked.mapped('emp_code'))])
        existing_codes = existing_employees.mapped('pin')
        not_linked = not_linked.filtered(lambda r: r.emp_code not in existing_codes)
        vals_list = []
        for record in not_linked:
            employee_vals = {
                'name': record.full_name,
                'pin': record.emp_code,
            }
            vals_list.append(employee_vals)
        if vals_list:
            self.env['hr.employee'].create(vals_list)
        return not_linked

    def cron_auto_link_hr_employee(self):
        not_linked = self.search([('employee_id', '=', False)])
        if not_linked:
            not_linked._compute_employee_id()
            _logger.info(f"Linked {len(not_linked)} ZK employees to HR employees.")