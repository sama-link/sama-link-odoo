from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    mission_id = fields.Many2one('hr.mission', string='Related Mission', help='The mission associated with this attendance record.')
    mission_generated = fields.Boolean(
        string='Mission Generated', default=False,
        help='Set when this attendance record was created by a mission (as opposed to '
             'a real check-in that a mission merged into). Mission-generated records are '
             'deleted when the mission is cancelled.')
    mission_orig_check_in = fields.Datetime(
        string='Pre-merge Check In',
        help='Original check-in before a mission merged its shift into this record. '
             'Used to restore the real attendance when the mission is cancelled.')
    mission_orig_check_out = fields.Datetime(
        string='Pre-merge Check Out',
        help='Original check-out before a mission merged its shift into this record. '
             'Used to restore the real attendance when the mission is cancelled.')