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

    def write(self, vals):
        if 'active' in vals and not vals['active']:
            if not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr.group_hr_manager'):
                from odoo.exceptions import UserError
                raise UserError("Only Administrators can archive contracts.")
        return super(HrContractInherit, self).write(vals)
