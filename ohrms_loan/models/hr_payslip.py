# -*- coding: utf-8 -*-
#############################################################################
#    A part of Open HRMS Project <https://www.openhrms.com>
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
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
from odoo import models
from odoo.tools.float_utils import float_compare


class HrPayslip(models.Model):
    """ Extends the 'hr.payslip' model to include
    additional functionality related to employee loans."""
    _inherit = 'hr.payslip'

    def get_inputs(self, contract_ids, date_from, date_to):
        """Compute additional inputs for the employee payslip,
        considering active loans.
        :param contract_ids: Contract ID of the current employee.
        :param date_from: Start date of the payslip.
        :param date_to: End date of the payslip.
        :return: List of dictionaries representing additional inputs for
        the payslip."""
        res = super(HrPayslip, self).get_inputs(contract_ids, date_from,
                                                date_to)
        employee_id = self.env['hr.contract'].sudo().browse(
            contract_ids[0].id).employee_id if contract_ids \
            else self.employee_id
        loan_lines = self.env['hr.loan.line'].search(
            [('date', '>=', date_from), ('date', '<=', date_to), ('paid', '=', False),
             ('loan_id.employee_id', '=', employee_id.id),
             ('loan_id.state', '=', 'approve')]
        )
        total_loan_amount = sum(loan_lines.mapped('amount'))
        for input in res:
            if input.get('code') == 'LO':
                input.update({'amount': total_loan_amount,
                              'loan_line_ids': [(4, line.id) for line in loan_lines]})        
        return res

    def _sync_loan_input_line_links(self):
        """Re-attach installments to LO inputs if payroll onchanges dropped m2m.

        Same domain as get_inputs; only links when slip amount matches the
        scheduled total so manual LO amounts are not overwritten wrongly.
        """
        LoanLine = self.env['hr.loan.line']
        for slip in self:
            currency = slip.company_id.currency_id
            prec = currency.rounding if currency else 0.01
            if not slip.employee_id or not slip.date_from or not slip.date_to:
                continue
            for inp in slip.input_line_ids.filtered(lambda l: l.code == 'LO'):
                if inp.loan_line_ids:
                    continue
                loan_lines = LoanLine.search([
                    ('date', '>=', slip.date_from),
                    ('date', '<=', slip.date_to),
                    ('paid', '=', False),
                    ('loan_id.employee_id', '=', slip.employee_id.id),
                    ('loan_id.state', '=', 'approve'),
                ])
                if not loan_lines:
                    continue
                total = sum(loan_lines.mapped('amount'))
                if float_compare(inp.amount, total, precision_rounding=prec) == 0:
                    inp.loan_line_ids = loan_lines

    def action_payslip_done(self):
        """ Compute the loan amount and remaining amount while confirming
            the payslip"""
        self._sync_loan_input_line_links()
        for line in self.input_line_ids:
            if line.loan_line_ids:
                line.loan_line_ids.write({'paid': True})
                line.loan_line_ids.loan_id.check_fully_paid()
        return super(HrPayslip, self).action_payslip_done()
