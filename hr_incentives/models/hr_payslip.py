import logging
from odoo import models, fields, api


_logger = logging.getLogger(__name__)

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    bonus_amount = fields.Float(
        string='Bonus Amount',
        compute='_compute_incentives_amount',
        help='Total bonus amount for the payslip period.',
    )
    penalty_amount = fields.Float(
        string='Penalty Amount',
        compute='_compute_incentives_amount',
        help='Total penalty amount for the payslip period.',
    )

    def _compute_incentives_amount(self):
        for payslip in self:
            incentives = self.env['hr.incentive'].sudo().search([
                ('employee_id', '=', payslip.employee_id.id),
                ('date', '>=', payslip.date_from),
                ('date', '<=', payslip.date_to),
                ('state', '=', 'approved'),
            ])
            payslip.bonus_amount = sum(incentives.filtered(lambda i: i.type == 'bonus').mapped('amount'))
            payslip.penalty_amount = sum(incentives.filtered(lambda i: i.type == 'penalty').mapped('amount'))