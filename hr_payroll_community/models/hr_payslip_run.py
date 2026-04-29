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
import json
from urllib.parse import quote
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

    @api.onchange('date_start', 'date_end')
    def _onchange_period_sync(self):
        """Instantly visually sync batch dates to all child payslips in UI"""
        if self.date_start and self.date_end:
            for slip in self.slip_ids:
                slip.date_from = self.date_start
                slip.date_to = self.date_end

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
        self.ensure_one()
        action = self.env.ref('hr_payroll_community.action_hr_payslip_line').sudo().read()[0]
        action['domain'] = [('slip_id.payslip_run_id', '=', self.id)]
        action['context'] = {'create': False}
        # Open in list first so users can select exact computation lines and export.
        action['view_mode'] = 'list,pivot,form'
        return action

    def action_export_batch_computation(self):
        """Open batch computation details in list view for export."""
        self.ensure_one()
        action = self.env.ref('hr_payroll_community.action_hr_payslip_line').sudo().read()[0]
        action['domain'] = [('slip_id.payslip_run_id', '=', self.id)]
        action['context'] = {'create': False}
        action['view_mode'] = 'list,pivot,form'
        return action

    def action_export_batch_finance_xlsx(self):
        """One-click export of batch payslips with finance template fields."""
        self.ensure_one()
        if not self.slip_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("No Payslips"),
                    'type': 'warning',
                    'message': _("There are no payslips in this batch to export."),
                }
            }

        # Pick export language from employees' linked users when possible.
        # If batch contains mixed languages, fall back to current UI context/user.
        employee_langs = {lang for lang in self.slip_ids.mapped('employee_id.user_id.lang') if lang}
        export_lang = self.env.context.get('lang') or self.env.user.lang or 'en_US'
        if len(employee_langs) == 1:
            export_lang = list(employee_langs)[0]
        is_arabic = (export_lang or '').startswith('ar')

        labels = {
            'employee_name': 'الموظف/اسم الموظف' if is_arabic else _('Employee/Employee Name'),
            'visa_no': 'الموظف/رقم التأشيرة' if is_arabic else _('Employee/Visa No'),
            'work_location': 'الموظف/موقع العمل/موقع العمل' if is_arabic else _('Employee/Work Location/Work Location'),
            'payment_method': 'العقد/طريقة دفع الراتب' if is_arabic else _('Contract/Salary Payment Method'),
            'net_amount': 'صافي المبلغ' if is_arabic else _('Net Amount'),
            'loan_advance': 'قرض/سلفة' if is_arabic else _('Loan/Advance'),
            'wage': 'الموظف/عقود الموظف/الأجر' if is_arabic else _('Employee/Employee Contracts/Wage'),
        }

        export_payload = {
            'model': 'hr.payslip',
            'ids': False,
            'domain': [('payslip_run_id', '=', self.id)],
            'fields': [
                {'name': 'employee_id/name', 'label': labels['employee_name'], 'type': 'char'},
                {'name': 'employee_id/visa_no', 'label': labels['visa_no'], 'type': 'char'},
                {'name': 'employee_id/work_location_id/name', 'label': labels['work_location'], 'type': 'char'},
                {'name': 'contract_id/salary_payment_method', 'label': labels['payment_method'], 'type': 'char'},
                {'name': 'net_amount', 'label': labels['net_amount'], 'type': 'float'},
                {'name': 'advance_amount', 'label': labels['loan_advance'], 'type': 'float'},
                {'name': 'contract_id/wage', 'label': labels['wage'], 'type': 'float'},
            ],
            'groupby': [],
            'import_compat': False,
            'context': dict(self.env.context),
        }
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/export/xlsx?data=%s' % quote(json.dumps(export_payload)),
            'target': 'self',
        }

    def action_view_payslip_inputs(self):
        """Open payslip inputs for the current batch for export."""
        self.ensure_one()
        action = self.env.ref('hr_payroll_community.action_hr_payslip_input').sudo().read()[0]
        # Keep all input codes visible (including LO); only filter by batch.
        action['domain'] = [('payslip_id.payslip_run_id', '=', self.id)]
        action['context'] = {'create': False}
        action['view_mode'] = 'list'
        return action

    def action_bulk_compute_payslips(self):
        failed = []
        for slip in self.slip_ids:
            try:
                with self.env.cr.savepoint():
                    slip.invalidate_recordset()
                    
                    # 1. Back up any manual inputs
                    saved_inputs = []
                    for il in slip.input_line_ids:
                        if il.amount != 0:
                            saved_inputs.append({
                                'name': il.name,
                                'code': il.code,
                                'amount': il.amount,
                                'contract_id': il.contract_id.id,
                                'sequence': il.sequence,
                            })
                            
                    # 2. Sync physical dates to match any fresh batch changes
                    slip.date_from = self.date_start
                    slip.date_to = self.date_end
                    
                    # 3. Regen working days / schedules / generic inputs for the NEW dates
                    slip.onchange_employee()
                    
                    # 4. Inject backed-up custom manual inputs securely 
                    for s_input in saved_inputs:
                        match = slip.input_line_ids.filtered(lambda l: l.code == s_input['code'])
                        if match:
                            match[0].amount = s_input['amount']
                        else:
                            slip.input_line_ids = [(0, 0, s_input)]
                            
                    # 5. Execute computation math with all perfect dates, manual values, and new rules
                    slip.action_compute_sheet()
            except Exception as e:
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