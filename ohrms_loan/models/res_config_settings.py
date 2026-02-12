from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    loan_allowed_dates_restrection = fields.Selection(
        selection=[
            ('none', 'No Restriction'),
            ('warning', 'Show Warning'),
            ('block', 'Block')
        ],
        string='Loan Application Date Restrictions',
        help='Set restrictions on loan applications based on specific days of the month.',
        config_parameter='ohrms_loan.loan_allowed_dates_restrection',
        default='none'
    )
    loan_after_month_day = fields.Integer(
        string='Allowed Loan After Month Day',
        help='Set the day of the month after which employees are allowed to apply for loans.',
        config_parameter='ohrms_loan.loan_after_month_day',
        default=10
    )
    loan_before_month_day = fields.Integer(
        string='Allowed Loan Before Month Day',
        help='Set the day of the month before which employees are allowed to apply for loans.',
        config_parameter='ohrms_loan.loan_before_month_day',
        default=20
    )
    loan_allowed_wage_percentage_restriction = fields.Selection(
        selection=[
            ('none', 'No Restriction'),
            ('warning', 'Show Warning'),
            ('block', 'Block')
        ],
        string='Loan Wage Percentage Restrictions',
        help='Set restrictions on loan amounts based on a percentage of the employee\'s wage.',
        config_parameter='ohrms_loan.loan_allowed_wage_percentage_restriction',
        default='none'
    )
    loan_max_wage_percentage = fields.Float(
        string='Maximum Loan Wage Percentage (%)',
        help='Set the maximum percentage of the employee\'s wage that can be granted as a loan.',
        config_parameter='ohrms_loan.loan_max_wage_percentage',
        default=50.0
    )
    loan_multi_request_restriction = fields.Selection(
        selection=[
            ('none', 'No Restriction'),
            ('warning', 'Show Warning'),
            ('block', 'Block')
        ],
        string='Multiple Loan Requests Restrictions',
        help='Set restrictions on multiple loan requests by the same employee.',
        config_parameter='ohrms_loan.loan_multi_request_restriction',
        default='none'
    )