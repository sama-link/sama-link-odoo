from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HrResignation(models.Model):
    _inherit = 'hr.resignation'

    def action_approve_resignation(self):
        # Check for uncleared custody
        for resignation in self:
            if resignation.employee_id:
                uncleared_custody = self.env['hr.custody'].search([
                    ('employee_id', '=', resignation.employee_id.id),
                    ('state', 'in', ['draft', 'received'])
                ])
                if uncleared_custody:
                    raise ValidationError(_('Cannot approve resignation. The employee has %s uncleared custody items.') % len(uncleared_custody))
        
        return super(HrResignation, self).action_approve_resignation()
