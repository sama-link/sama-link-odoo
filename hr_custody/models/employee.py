from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HrContract(models.Model):
    _inherit = 'hr.contract'

    custody_ids = fields.One2many('hr.custody', 'contract_id', string='Custody Items')

    def write(self, vals):
        if ('state' in vals and vals['state'] in ['close', 'cancel']) or ('active' in vals and not vals['active']):
            for contract in self:
                uncleared = self.env['hr.custody'].search([
                    ('contract_id', '=', contract.id),
                    ('state', 'in', ['draft', 'received'])
                ])
                if uncleared:
                    raise ValidationError(_('Cannot close or archive contract! The employee has %s uncleared custody items linked to this contract.') % len(uncleared))
        return super(HrContract, self).write(vals)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    custody_ids = fields.One2many('hr.custody', 'employee_id', string='Custody')
    custody_count = fields.Integer(string='Custody Count', compute='_compute_custody_count')

    @api.depends('custody_ids.state')
    def _compute_custody_count(self):
        for employee in self:
            # Only count uncleared items? Or all? User said "clear also from employee card"
            # I will count only uncleared.
            employee.custody_count = self.env['hr.custody'].search_count([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['draft', 'received'])
            ])

    def action_view_custody(self):
        self.ensure_one()
        return {
            'name': 'Custody',
            'type': 'ir.actions.act_window',
            'view_mode': 'list,form',
            'res_model': 'hr.custody',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def write(self, vals):
        if 'active' in vals and not vals['active']:
             for employee in self:
                uncleared = self.env['hr.custody'].search([
                    ('employee_id', '=', employee.id),
                    ('state', 'in', ['draft', 'received'])
                ])
                if uncleared:
                    raise ValidationError(_('Cannot archive employee! The employee has %s uncleared custody items.') % len(uncleared))
        return super(HrEmployee, self).write(vals)
