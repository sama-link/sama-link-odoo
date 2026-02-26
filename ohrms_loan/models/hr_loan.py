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
from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class HrLoan(models.Model):
    """ Model for managing loan requests."""
    _name = 'hr.loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Loan Request"
    _check_company_auto = True

    @api.model
    def default_get(self, field_list):
        """ Function used to pass employee corresponding to current login user
            as default employee while creating new loan request
            :param field_list : Fields and values for the model hr.loan"""
        result = super(HrLoan, self).default_get(field_list)
        if result.get('user_id'):
            user_id = result['user_id']
        else:
            user_id = self.env.context.get('user_id', self.env.user.id)
        result['employee_id'] = self.env['hr.employee'].search(
            [('user_id', '=', user_id)], limit=1).id
        return result

    name = fields.Char(string="Loan Name", default="New", readonly=True,
                       help="Name of the loan")
    date = fields.Date(string="Date", default=fields.Date.today(),
                       readonly=True, help="Date of the loan request")
    employee_id = fields.Many2one('hr.employee', string="Employee",
                                  required=True, help="Employee Name", tracking=True)
    department_id = fields.Many2one('hr.department',
                                    related="employee_id.department_id",
                                    readonly=True,
                                    string="Department",
                                    help="The department to which the "
                                         "employee belongs.")
    installment = fields.Integer(string="No Of Installments", default=1,
                                 help="Number of installments", tracking=True)
    payment_date = fields.Date(string="Payment Start Date", required=True,
                               default=fields.Date.today(),
                               help="Date of the payment", tracking=True)
    loan_lines = fields.One2many('hr.loan.line', 'loan_id',
                                 string="Loan Line",
                                 help="Details of installment lines "
                                      "associated with the loan.",
                                 index=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 help="Company",
                                 default=lambda self: self.env.user.company_id)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  required=True, help="Currency",
                                  default=lambda self: self.env.user.
                                  company_id.currency_id, tracking=True)
    job_position_id = fields.Many2one('hr.job',
                                   related="employee_id.job_id",
                                   readonly=True, string="Job Position",
                                   help="Job position of the employee")
    loan_amount = fields.Float(string="Loan Amount", required=True,
                               help="Loan amount", tracking=True)
    total_amount = fields.Float(string="Total Amount", store=True,
                                readonly=True, compute='_compute_total_amount',
                                help="The total amount of the loan", tracking=True)
    balance_amount = fields.Float(string="Balance Amount", store=True,
                                  compute='_compute_total_amount',
                                  help="""The remaining balance amount of the
                                  loan after deducting
                                  the total paid amount.""", tracking=True)
    total_paid_amount = fields.Float(string="Total Paid Amount", store=True,
                                     compute='_compute_total_amount',
                                     help="The total amount that has been "
                                          "paid towards the loan.", tracking=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('waiting_approval_1', 'Submitted'),
         ('approve', 'Approved'), ('refuse', 'Refused'), ('cancel', 'Canceled'), ('paid', 'Fully Paid')
         ], string="State", default='draft', help="The current state of the "
                                                  "loan request.", copy=False, tracking=True)
    work_location_id = fields.Many2one(related="employee_id.work_location_id", domain="[('address_id', '=', address_id)]")
    active = fields.Boolean(default=True, tracking=True)
    deleted = fields.Boolean(default=False)
    multi_request_warning_shown = fields.Boolean(default=False, compute='_compute_check_pending_loan')
    max_loan_amount_warning_shown = fields.Boolean(default=False, compute='_compute_check_max_loan_amount')
    date_restriction_warning_shown = fields.Boolean(default=False, compute='_compute_check_date')

    def check_fully_paid(self):
        self._compute_total_amount()
        for loan in self:
            if loan.state == 'approve' and loan.balance_amount == 0:
                loan.write({'state': 'paid'})
                loan.action_archive()
            elif loan.state == 'paid' and loan.balance_amount > 0:
                loan.write({'state': 'approve', 'active': True})

    def action_mark_as_paid(self):
        self.loan_lines.filtered(lambda line: not line.paid).write({'paid': True})
        self.check_fully_paid()

    def action_pay_amount(self):
        return {
            'name': _('Pay Loan Amount'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'hr.loan.pay.amount.wizard',
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
            }
        }

    def action_archive(self):
        for record in self:
            if record.state not in ['draft', 'cancel', 'paid']:
                raise ValidationError("You cannot delete a loan which is not in draft, cancelled, or fully paid state.")
        return super(HrLoan, self).action_archive()

    def action_unarchive(self):
        for record in self:
            if record.deleted:
                raise ValidationError("You cannot unarchive a deleted loan.")
        return super(HrLoan, self).action_unarchive()

    @api.constrains('employee_id')
    def _check_pending_loan(self):
        loan_multi_request_restriction = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_multi_request_restriction', default='none')
        if loan_multi_request_restriction == 'block':
            self.__check_has_pending_loan()

    @api.depends('employee_id')
    def _compute_check_pending_loan(self):
        self.write({'multi_request_warning_shown': False})
        loan_multi_request_restriction = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_multi_request_restriction', default='none')
        if loan_multi_request_restriction == 'warning':
            self.__check_has_pending_loan(raise_error=False)

    def __check_has_pending_loan(self, raise_error=True):
        is_admin = self.env.user.has_group('ohrms_loan.group_loan_bypass_restrictions')
        if is_admin:
            return
        for loan in self:
            pending_loan_count = self.env['hr.loan'].search_count([
                ('employee_id', '=', loan.employee_id.id),
                ('state', '=', 'approve'),
                ('balance_amount', '!=', 0),
            ])
            if pending_loan_count:
                if raise_error:
                    raise ValidationError(
                        _("The Employee has already a pending installment"))
                else:
                    loan.multi_request_warning_shown = True
                    continue
            draft_loan_count = self.env['hr.loan'].search_count([
                ('employee_id', '=', loan.employee_id.id),
                ('state', '=', 'draft')
            ])
            if draft_loan_count > 1:
                if raise_error:
                    raise ValidationError(
                        _("The Employee has already a draft loan request"))
                else:
                    loan.multi_request_warning_shown = True
                    continue

    @api.constrains('employee_id', 'loan_amount')
    def _check_max_loan_amount(self):
        loan_allowed_wage_percentage_restriction = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_allowed_wage_percentage_restriction', default='none')
        if loan_allowed_wage_percentage_restriction == 'block':
            self.__check_max_loan_amount()

    @api.depends('employee_id', 'loan_amount')
    def _compute_check_max_loan_amount(self):
        self.write({'max_loan_amount_warning_shown': False})
        loan_allowed_wage_percentage_restriction = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_allowed_wage_percentage_restriction', default='none')
        if loan_allowed_wage_percentage_restriction == 'warning':
            self.__check_max_loan_amount(raise_error=False)

    def __check_max_loan_amount(self, raise_error=True):
        is_admin = self.env.user.has_group('ohrms_loan.group_loan_bypass_restrictions')
        if is_admin:
            return
        loan_max_wage_percentage = float(self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_max_wage_percentage', default=0)) / 100
        for loan in self:
            max_loan = int(loan.employee_id.sudo().contract_id.wage) * (loan_max_wage_percentage or 1)
            if not max_loan and raise_error:
                raise ValidationError(
                    _("The employee does not have a valid contract "
                      "with a defined wage."))
            elif loan.loan_amount > max_loan and raise_error:
                raise ValidationError(
                    _("The loan amount exceeds the maximum limit of %s "
                      "for the employee.") % max_loan)
            else:
                loan.max_loan_amount_warning_shown = loan.loan_amount > max_loan

    @api.constrains('date')
    def _check_date(self):
        loan_allowed_dates_restrection = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_allowed_dates_restrection', default='none')
        if loan_allowed_dates_restrection == 'block':
            self.__check_date()

    def _compute_check_date(self):
        self.write({'date_restriction_warning_shown': False})
        loan_allowed_dates_restrection = self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_allowed_dates_restrection', default='none')
        if loan_allowed_dates_restrection == 'warning':
            self.write({'date_restriction_warning_shown': self.__check_date(raise_error=False)})

    def __check_date(self, raise_error=True):
        is_admin = self.env.user.has_group('ohrms_loan.group_loan_bypass_restrictions')
        if is_admin:
            return
        today = fields.Date.today().day
        loan_after_day = int(self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_after_month_day', default=10))
        loan_before_day = int(self.env['ir.config_parameter'].sudo().get_param('ohrms_loan.loan_before_month_day', default=20))
        if today < loan_after_day or today > loan_before_day:
            if raise_error:
                raise ValidationError(
                    _("You can only create loan request between "
                      "%s to %s of the month.") % (loan_after_day, loan_before_day))
            else:
                return True

    @api.depends('loan_lines.paid', 'loan_lines.amount', 'loan_amount')
    def _compute_total_amount(self):
        """ Compute total loan amount,balance amount and total paid amount"""
        total_paid = 0.0
        for loan in self:
            for line in loan.loan_lines:
                if line.paid:
                    total_paid += line.amount
            balance_amount = loan.loan_amount - total_paid
            loan.total_amount = loan.loan_amount
            loan.balance_amount = balance_amount
            loan.total_paid_amount = total_paid

    @api.model
    def create(self, values):
        """ Check whether any pending loan is for the employee and calculate
            the sequence
            :param values : Dictionary which contain fields and values"""
        
        values['name'] = self.env['ir.sequence'].get('hr.loan.seq') or ' '
        return super(HrLoan, self).create(values)

    def action_compute_installment(self):
        """This automatically create the installment the employee need to pay to
            company based on payment start date and the no of installments.
            """
        for loan in self:
            loan.loan_lines.unlink()
            date_start = datetime.strptime(str(loan.payment_date), '%Y-%m-%d')
            amount = loan.loan_amount / loan.installment
            for i in range(1, loan.installment + 1):
                self.env['hr.loan.line'].create({
                    'date': date_start,
                    'amount': amount,
                    'employee_id': loan.employee_id.id,
                    'loan_id': loan.id})
                date_start = date_start + relativedelta(months=1)
            loan._compute_total_amount()
        return True

    def action_refuse(self):
        """ Function to reject loan request"""
        return self.write({'state': 'refuse'})

    def action_submit(self):
        """ Function to submit loan request"""
        self.write({'state': 'waiting_approval_1'})

    def action_cancel(self):
        """ Function to cancel loan request"""
        self.write({'state': 'cancel'})

    def action_approve(self):
        """ Function to approve loan request"""
        for data in self:
            if not data.loan_lines:
                raise ValidationError(_("Please Compute installment"))
            else:
                self.write({'state': 'approve'})

    def unlink(self):
        """ Function which restrict the deletion of approved or submitted
                loan request"""
        for loan in self:
            if loan.state not in ('draft', 'cancel'):
                raise UserError(_(
                    'You cannot delete a loan which is not in draft '
                    'or cancelled state'))
        for record in self:
            record.message_post(body="Loan record has been deleted.")
        self.write({'active': False, 'deleted': True})
        return True
