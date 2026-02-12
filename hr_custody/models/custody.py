from odoo import models, fields, api, _
from datetime import date

class HrCustody(models.Model):
    _name = 'hr.custody'
    _description = 'Employee Custody'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', compute='_compute_name', store=True, readonly=True)

    @api.depends('employee_id', 'custody_type_id')
    def _compute_name(self):
        for rec in self:
            if rec.employee_id and rec.custody_type_id:
                rec.name = f"{rec.custody_type_id.name} - {rec.employee_id.name}"
            else:
                rec.name = _('New Custody')

    custody_type_id = fields.Many2one('hr.custody.type', string='Custody Type')
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    contract_id = fields.Many2one('hr.contract', string='Contract')
    date_receive = fields.Date(string='Receive Date', required=True, default=fields.Date.today)
    date_return = fields.Date(string='Return Date')
    image = fields.Binary(string='Image')
    note = fields.Text(string='Notes')
    value = fields.Float(string='Estimated Value')
    active = fields.Boolean(default=True, string='Active')
    custody_image_ids = fields.One2many('hr.custody.image', 'custody_id', string='Images')
    custody_document = fields.Binary(string='custody document', attachment=True)
    custody_document_name = fields.Char(string='custody document Name')
    state = fields.Selection([
        ('received', 'Received'),
        ('cleared', 'Cleared')
    ], string='Status', default='received', track_visibility='onchange')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            # Find running contract
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', self.employee_id.id),
                ('state', '=', 'open')
            ], limit=1)
            if contract:
                self.contract_id = contract.id

    def action_clear(self):
        for rec in self:
            rec.state = 'cleared'
            rec.date_return = date.today()


class HrCustodyImage(models.Model):
    _name = 'hr.custody.image'
    _description = 'Custody Image'

    custody_id = fields.Many2one('hr.custody', string='Custody', required=True, ondelete='cascade')
    image = fields.Binary(string='Image', required=True)
    name = fields.Char(string='Description')
