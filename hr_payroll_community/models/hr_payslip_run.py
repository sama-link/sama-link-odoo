# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import fields, models, _, api

_logger = logging.getLogger(__name__)


class HrPayslipRun(models.Model):
    """Create new model for getting Payslip Batches"""
    _name = 'hr.payslip.run'
    _description = 'Payslip Batches'

    name = fields.Char(required=True, help="Name for Payslip Batches",
                       string="Name")
    slip_ids = fields.One2many('hr.payslip',
                               'payslip_run_id',
                               string='Payslips',
                               help="Choose Payslips for Batches")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('close', 'Close'),
    ], string='Status', index=True, readonly=True, copy=False, default='draft',
                               help="Status for Payslip Batches")
    date_start = fields.Date(string='Date From', required=True,
                             help="start date for batch",
                             default=lambda self: fields.Date.to_string(
                                 date.today().replace(day=1)))
    date_end = fields.Date(string='Date To', required=True,
                           help="End date for batch",
                           default=lambda self: fields.Date.to_string(
                               (datetime.now() + relativedelta(months=+1, day=1,
                                                               days=-1)).date())
                           )
    duration = fields.Integer(string='Duration (Days)', compute='_compute_duration',
                            help="Duration in Days", store=True, readonly=True)
    rest_days_adjustment = fields.Integer(string='Rest Days Adjustment', help="Number of rest days to be adjusted in the payslip calculation",)
    credit_note = fields.Boolean(string='Credit Note',
                                 help="If its checked, indicates that all"
                                      "payslips generated from here are refund"
                                      "payslips.")

    payslip_count = fields.Integer(compute='_compute_payslip_count',
                                   string="Payslip Computation Details",
                                   help="Set Payslip Count")

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for record in self:
            delta = 0
            if record.date_start and record.date_end:
                delta = (record.date_end - record.date_start).days + 1
            record.duration = delta

    def _compute_payslip_count(self):
        """Function to compute payslip count"""
        for payslip_run in self:
            payslip_run.payslip_count = self.env['hr.payslip'].search_count(
                [('payslip_run_id', '=', payslip_run.id)])

    def action_payslip_run(self):
        """Function for state change"""
        return self.write({'state': 'draft'})

    def close_payslip_run(self):
        """Function for state change"""
        self.slip_ids.action_payslip_done()
        return self.write({'state': 'close'})

    def action_view_payslips(self):
        """Function to view payslips in batch"""
        action = self.env.ref('hr_payroll_community.action_hr_payslip_line').sudo().read()[0]
        action['domain'] = [('slip_id.payslip_run_id', '=', self.id)]
        action['context'] = {'create': False}
        action['view_mode'] = 'pivot,form'
        return action

    def action_bulk_compute_payslips(self):
        failed = []
        for slip in self.slip_ids:
            try:
                savepoint = self.env.cr.savepoint()
                slip.action_compute_sheet()
                savepoint.close()
            except Exception as e:
                savepoint.rollback()
                _logger.warning(
                    "Failed to compute payslip for %s (ID: %s): %s",
                    slip.employee_id.name, slip.id, e
                )
                failed.append(slip.employee_id.name or str(slip.id))
        if failed:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Partial Success"),
                    'type': 'warning',
                    'message': _("Computed successfully except for: %s") % ', '.join(failed),
                    'sticky': True,
                }
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Success"),
                'type': 'success',
                'message': _("All payslips have been successfully computed."),
            }
        }