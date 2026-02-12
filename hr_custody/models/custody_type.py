from odoo import models, fields

class HrCustodyType(models.Model):
    _name = 'hr.custody.type'
    _description = 'Custody Type'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    # value = fields.Float(string='Estimated Value')
    description = fields.Text(string='Description')
