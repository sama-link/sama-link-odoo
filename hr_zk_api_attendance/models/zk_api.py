import json
import requests
import logging
from urllib.parse import quote
from datetime import date
from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

class ZkApi(models.Model):
    _name = 'zk.api'
    _description = 'ZK API'

    name = fields.Char(string='Name', required=True)
    url = fields.Char(string='URL', required=True)
    username = fields.Char(string='Username', required=True)
    password = fields.Char(string='Password', required=True)
    token = fields.Char(string='Token', copy=False, readonly=True)
    is_set_up = fields.Boolean(string='Is Set up', default=False, copy=False, readonly=True)
    active = fields.Boolean(string='Active', default=True)

    def _get_headers(self, renew_token=False):
        """Function to get the headers for API requests"""
        try:
            token = self.token
            if not token or renew_token:
                self.action_generate_token()
                token = self.token
        except Exception as e:
            _logger.error(f"Error getting auth token: {e}")
            raise UserError(_("Failed to get authentication token."))
        return {
            'Authorization': f'Token {token}',
            'Content-Type': 'application/json'
        }

    def _get_auth_token(self):
        endpoint = "/api-token-auth/"
        url = f"{self.url}{endpoint}"
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "username": self.username,
            "password": self.password
        }

        response = requests.post(url, data=json.dumps(data), headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        return response.json().get('token')

    def action_first_setup(self):
        """Function to perform the first setup"""
        headers = self._get_headers()
        self.env['zk.department'].sync_departments(headers, self.url)
        self.env['zk.employee'].sync_employees(headers, self.url)
        self.is_set_up = True

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_sync_departments(self):
        """Function to set departments from ZK API"""
        headers = self._get_headers()
        self.env['zk.department'].sync_departments(headers, self.url)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
            'title': _('Success'),
            'message': _('Departments synchronized successfully.'),
            'type': 'success',
            'sticky': False,
            }
        }

    def action_sync_attendance(self, cron=False, start_date=None, end_date=None, departments=None, employees=None):
        """Function to set attendance from ZK API"""
        headers = self._get_headers()
        attendance_ids = self.env['zk.attendance'].sync_attendance(headers, self.url, start_date=start_date, end_date=end_date, departments=departments, employees=employees)
        if cron:
            return attendance_ids
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Attendance synchronized successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_sync_employees(self):
        """Function to set employees from ZK API"""
        headers = self._get_headers()
        self.env['zk.employee'].sync_employees(headers, self.url)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Employees synchronized successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_generate_token(self):
        """Function to set the token manually"""
        token = self._get_auth_token()
        self.token = token  # Store the token for future use

    def cron_auto_sync_attendance(self):
        """Cron job to automatically sync attendance"""
        for api in self.search([('active', '=', True), ('is_set_up', '=', True)]):
            try:
                attendance_ids = api.action_sync_attendance(cron=True)
                _logger.info(f"Attendance records synced: {len(attendance_ids)}")
            except Exception as e:
                _logger.error(f"Error during cron auto sync attendance: {e}")

    def cron_auto_sync_employees(self):
        """Cron job to automatically sync employees"""
        for api in self.search([('active', '=', True), ('is_set_up', '=', True)]):
            try:
                api.action_sync_employees()
                _logger.info("Employees synced successfully via cron.")
            except Exception as e:
                _logger.error(f"Error during cron auto sync employees: {e}")