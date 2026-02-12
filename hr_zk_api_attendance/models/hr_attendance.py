from odoo import models, fields


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    zk_attendance_ids = fields.One2many(
        'zk.attendance',
        'hr_attendance_id',
        string='ZK Attendance Records',
        help='ZK Attendance records associated with this HR Attendance',
        readonly=True,
    )
    in_out_validity = fields.Selection(selection=[
        ('invalid', 'Invalid'),
        ('valid', 'Valid'),
    ], default='valid', string='Check-in/Check-out Validity', help='Validity of the check-in and check-out times.', readonly=True)