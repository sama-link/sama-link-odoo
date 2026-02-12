from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    mission_id = fields.Many2one('hr.mission', string='Related Mission', help='The mission associated with this attendance record.')