from odoo import api, fields, models, _
from odoo.exceptions import UserError

class HrLoanAddInstallmentWizard(models.TransientModel):
    _name = 'hr.loan.add.installment.wizard'
    _description = 'Loan Add Installment Wizard'

    loan_id = fields.Many2one('hr.loan', string='Loan', required=True)
    currency_id = fields.Many2one(related='loan_id.currency_id', readonly=True)
    total_amount = fields.Float(string='Total Amount', related='loan_id.total_amount', readonly=True)
    balance_amount = fields.Float(string='Remaining Amount', related='loan_id.balance_amount', readonly=True)
    date = fields.Date(string='Payment Date', required=True, default=fields.Date.context_today)
    amount = fields.Float(string='Amount', required=True)

    @api.constrains('amount')
    def _check_amount(self):
        for wizard in self:
            if wizard.amount <= 0:
                raise UserError(_('The installment amount must be positive.'))

    def do_action(self):
        self.ensure_one()
        loan = self.loan_id
        self.env['hr.loan.line'].create({
            'date': self.date,
            'amount': self.amount,
            'employee_id': loan.employee_id.id,
            'loan_id': loan.id,
        })
        loan.write({
            'loan_amount': loan.loan_amount + self.amount,
            'installment': loan.installment + 1,
        })
        loan.check_fully_paid()
        return {'type': 'ir.actions.act_window_close'}
