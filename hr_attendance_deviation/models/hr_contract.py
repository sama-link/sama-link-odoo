from odoo import models, fields

class HrContract(models.Model):
    _inherit = 'hr.contract'

    multi_shifts = fields.Boolean(string='Multi Shifts', default=False)
    resource_calendar_ids = fields.Many2many('resource.calendar', string='Allowed Working Schedules', domain="[('id', '!=', resource_calendar_id)]")