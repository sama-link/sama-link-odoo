from odoo import models, fields

class HrContractInherit(models.Model):
    _inherit = 'hr.contract'

    salary_payment_method = fields.Selection([
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('other', 'Other')
    ], string="Salary Payment Method", default='bank_transfer', required=True)
    not_listed_payment_method = fields.Char(string="If Other, specify")
    work_location_id = fields.Many2one(related="employee_id.work_location_id", domain="[('address_id', '=', address_id)]")
