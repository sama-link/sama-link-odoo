import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api
from odoo.exceptions import ValidationError
from odoo.addons.hr_attendance_deviation.tools import Converter


_logger = logging.getLogger(__name__)

class HrMission(models.Model):
    _name = 'hr.mission'
    _inherit = ['mail.thread']
    _description = 'HR Mission'
    _rec_name = 'employee_id'
    _check_company_auto = True

    active = fields.Boolean(default=True, string='Active')


    def _default_employee(self):
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        return employee.id if employee else False

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, default=_default_employee)
    company_id = fields.Many2one('res.company', related='employee_id.company_id', string='Company', store=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id')
    current_location_id = fields.Many2one('hr.work.location', related='employee_id.work_location_id')
    manager_id = fields.Many2one('hr.employee', string='Manager', related='employee_id.parent_id')
    start_date = fields.Date(string='Mission Start Date', required=True, default=fields.Date.context_today, tracking=True)
    end_date = fields.Date(string='Mission End Date', required=True, default=fields.Date.context_today, tracking=True)
    destination = fields.Char(string='Destination', required=True, tracking=True)
    mission_type = fields.Selection([
        ('installation', 'Installation'),
        ('maintenance', 'Maintenance'),
        ('other', 'Other')
    ], string='Mission Type', required=True, tracking=True)
    note = fields.Text(string='Additional Notes', tracking=True)
    hr_reason = fields.Text(string='Reason of Approval/Rejection (HR)', tracking=True)
    state = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('hr_approved', 'HR Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='confirmed', tracking=True)
    attendance_ids = fields.One2many('hr.attendance', 'mission_id', string='Attendance Records', readonly=True)

    def action_hr_approve(self):
        if not self.env.user.has_group('hr_mission.group_hr_mission_manager'):
            raise ValidationError("You have to be a HR responsible to approve this request.")
        self._create_attendance_records()
        self.write({'state': 'hr_approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_cancel(self):
        # Undo the attendance changes made on approval, without destroying real check-ins.
        linked = self.env['hr.attendance'].search([('mission_id', 'in', self.ids)])
        # Purely mission-generated records (no real check-in behind them) are removed.
        linked.filtered('mission_generated').unlink()
        # Records the mission merged into a real check-in are restored to their original times.
        for attendance in linked.filtered(lambda a: not a.mission_generated):
            attendance.write({
                'check_in': attendance.mission_orig_check_in or attendance.check_in,
                'check_out': attendance.mission_orig_check_out,
                'mission_id': False,
                'mission_orig_check_in': False,
                'mission_orig_check_out': False,
            })
        self.write({'state': 'cancelled'})

    def _create_attendance_records(self):
        found_shift = False
        for record in self:
            current_date = record.start_date
            while current_date <= record.end_date:
                shift_vals = record._get_shift_start_end(current_date)
                if shift_vals:
                    found_shift = True
                    record._apply_mission_attendance(current_date, shift_vals)
                current_date += timedelta(days=1)
        if not found_shift:
            raise ValidationError("No attendance shifts found for the mission period. Please ensure attendance shifts are recorded before approving the mission.")

    def _apply_mission_attendance(self, date, shift_vals):
        """ Create or merge the mission's shift attendance for a single day.

        If the employee already has attendance on that day, merge everything into one
        record using the earliest check-in and latest check-out ("first check-in, last
        check-out") instead of creating a conflicting/overlapping record. """
        self.ensure_one()
        Attendance = self.env['hr.attendance']
        shift_start = shift_vals['check_in']
        shift_end = shift_vals['check_out']
        day_start = self._convert_to_gmt_naive(date, time.min)
        day_end = self._convert_to_gmt_naive(date, time.max)
        existing = Attendance.search([
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '>=', day_start),
            ('check_in', '<=', day_end),
        ])
        if not existing:
            Attendance.create(dict(shift_vals, mission_generated=True))
            return
        first_check_in = min(existing.mapped('check_in') + [shift_start])
        last_check_out = max([co for co in existing.mapped('check_out') if co] + [shift_end])
        keep = existing.sorted('check_in')[0]
        (existing - keep).unlink()
        keep.write({
            'mission_orig_check_in': keep.check_in,
            'mission_orig_check_out': keep.check_out,
            'check_in': first_check_in,
            'check_out': last_check_out,
            'mission_id': self.id,
            'mission_generated': False,
        })

    def _get_shift_start_end(self, date):
        contract = self.employee_id.contract_id
        attendances = contract.resource_calendar_id.attendance_ids
        dayofweek = str(date.weekday())
        dayofweek_attendance = attendances.filtered(lambda at: str(at.dayofweek) == dayofweek)
        shift_start_datetime, shift_end_datetime = self._get_shift_datetimes(dayofweek_attendance, date)
        if dayofweek_attendance:
            return{
                'employee_id': self.employee_id.id,
                'check_in': shift_start_datetime,
                'check_out': shift_end_datetime,
                'mission_id': self.id
            }

    def _get_shift_datetimes(self, shift, date):
        shift_hour_from_time = self._convert_float_to_time(shift.hour_from)
        shift_hour_to_time = self._convert_float_to_time(shift.hour_to)
        shift_start_datetime = self._convert_to_gmt_naive(date, shift_hour_from_time)
        shift_end_datetime = self._convert_to_gmt_naive(date, shift_hour_to_time)
        return shift_start_datetime, shift_end_datetime

    def _convert_float_to_time(self, float_time):
        return Converter.float_to_time_obj(float_time)

    def _convert_to_gmt_naive(self, date_obj, time_obj):
        return Converter.date_time_to_gmt_naive(date_obj, time_obj)
