<<<<<<< HEAD
from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

=======
from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

>>>>>>> 4717772238b15978793a2220ea43cb98d4ca4deb
    mission_id = fields.Many2one('hr.mission', string='Related Mission', help='The mission associated with this attendance record.')