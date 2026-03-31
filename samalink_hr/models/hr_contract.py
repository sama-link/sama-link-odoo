from odoo import models, fields, _
from odoo.exceptions import UserError, ValidationError

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
        is_archiving = ('active' in vals and not vals['active'])
        is_closing = ('state' in vals and vals['state'] in ['close', 'cancel'])
        if is_archiving or is_closing:
            # Block if employee has unpaid/active loans (same idea as custody blocking).
            if 'hr.loan' in self.env.registry.models:
                for contract in self:
                    if not contract.employee_id:
                        continue
                    pending_loans = self.env['hr.loan'].search_count([
                        ('employee_id', '=', contract.employee_id.id),
                        '|',
                        ('state', 'in', ['draft', 'waiting_approval_1']),
                        '&',
                        ('state', '=', 'approve'),
                        ('balance_amount', '>', 0),
                    ])
                    if pending_loans:
                        raise ValidationError(
                            _("Cannot close or archive contract! The employee has %s unpaid or pending loan(s).") % pending_loans
                        )

        if is_archiving:
            if (not self.env.user.has_group('base.group_system')
                    and not self.env.user.has_group('hr.group_hr_manager')):
                raise UserError(_("Only Administrators can archive contracts."))
        return super(HrContractInherit, self).write(vals)
