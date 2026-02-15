from odoo import models, fields, api, _
from datetime import date


class HrCustodyReturnWizard(models.TransientModel):
    _name = 'hr.custody.return.wizard'
    _description = 'Custody Return Wizard'

    custody_id = fields.Many2one('hr.custody', string='Custody', required=True)
    return_status = fields.Selection([
        ('same', 'Same as original status'),
        ('different', 'Not in the same old status'),
    ], string='Custody Return Status', required=True)
    current_estimated_value = fields.Float(string='Current Estimated Value')
    description = fields.Text(string='Description')

    def action_confirm(self):
        self.ensure_one()
        custody = self.custody_id
        custody.write({
            'state': 'cleared',
            'date_return': date.today(),
            'value': self.current_estimated_value,
        })
        return {'type': 'ir.actions.act_window_close'}
