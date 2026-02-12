from odoo import api, fields, models, _
from odoo.exceptions import UserError

class HrLoanPayAmountWizard(models.TransientModel):
    _name = 'hr.loan.pay.amount.wizard'
    _description = 'Loan Pay Amount Wizard'

    loan_id = fields.Many2one('hr.loan', string='Loan', required=True)
    balance_amount = fields.Float(string='Remaining Amount', related='loan_id.balance_amount', readonly=True)
    amount = fields.Float(string='Amount to Pay', required=True)

    @api.constrains('amount')
    def _check_amount(self):
        for wizard in self:
            if wizard.amount <= 0:
                raise UserError(_('The payment amount must be positive.'))
            if wizard.loan_id and wizard.amount > wizard.balance_amount:
                raise UserError(_('The payment amount cannot exceed the remaining loan amount.'))

    def do_action(self):
        self.ensure_one()
        loan = self.loan_id
        if self.amount > self.balance_amount:
            raise UserError(_('Payment amount exceeds the remaining loan amount.'))
        # Create a payment record (assuming a model exists)
        unpaid_lines = loan.loan_lines.filtered(lambda l: not l.paid)
        amount_to_pay = self.amount
        for line in unpaid_lines:
            if amount_to_pay <= 0:
                break
            line_amount = line.amount
            if amount_to_pay >= line_amount:
                line.paid = True
                amount_to_pay -= line_amount
            else:
                line.amount -= amount_to_pay
                loan.loan_lines += line.copy({'amount': amount_to_pay, 'paid': True, 'date': fields.Date.context_today(self)})
                amount_to_pay = 0
        loan.check_fully_paid()
        return {'type': 'ir.actions.act_window_close'}