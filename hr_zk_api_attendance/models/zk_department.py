import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ZkDepartment(models.Model):
    _name = 'zk.department'
    _description = 'ZK Department'
    _rec_name = 'dept_name'

    zk_id = fields.Char(string='Department ID', required=True)
    dept_name = fields.Char(string='Name', required=True)
    dept_code = fields.Char(string='Code', required=True)
    active = fields.Boolean(string='Active', default=True)

    @api.model
    def _get_departments(self, headers, api_url):
        endpoint = "/personnel/api/departments/"
        url = f"{api_url}{endpoint}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses
        return response.json().get("data")

    @api.model
    def sync_departments(self, headers, api_url):
        """Function to sync departments from ZK API"""
        try:
            departments_data = self._get_departments(headers, api_url)
        except requests.exceptions.HTTPError as e:
            _logger.error(f"Error fetching departments: {e}")
            raise UserError(_("Failed to fetch departments from ZK API."))

        if not departments_data:
            _logger.warning("No departments found in ZK API response.")
            return

        existing_departments = self.search([]).mapped("zk_id")
        for dep in departments_data:
            if str(dep['id']) not in existing_departments:
                self.create({
                    'zk_id': dep['id'],
                    'dept_name': dep['dept_name'],
                    'dept_code': dep['dept_code']
                })
        _logger.info("Departments successfully synced from ZK API.")
