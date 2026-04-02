from odoo import models, _
from odoo.exceptions import ValidationError


class HrContract(models.Model):
    _inherit = 'hr.contract'

    def write(self, vals):
        # Block closing/cancelling/archiving contracts when employee has unpaid loans.
        if (('state' in vals and vals['state'] in ['close', 'cancel'])
                or ('active' in vals and not vals['active'])):
            for contract in self:
                if not contract.employee_id:
                    continue
                pending_loans = self.env['hr.loan'].search_count([
                    ('employee_id', '=', contract.employee_id.id),
                    ('state', '=', 'approve'),
                    ('balance_amount', '!=', 0),
                ])
                if pending_loans:
                    raise ValidationError(
                        _('Cannot close or archive contract! The employee has %s unpaid loan(s).')
                        % pending_loans
                    )
        return super(HrContract, self).write(vals)

