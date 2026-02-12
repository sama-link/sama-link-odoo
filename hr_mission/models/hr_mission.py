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

    @api.constrains('employee_id')
    def _check_one_mission(self):
        for record in self:
            existing_missions = self.search_count([
                ('employee_id', '=', record.employee_id.id),
                ('state', '=', 'confirmed'),
                ('id', '!=', record.id)
            ])
            if existing_missions:
                raise ValidationError("There is already an ongoing mission request for this employee.")

    def action_hr_approve(self):
        if not self.env.user.has_group('hr_mission.group_hr_mission_manager'):
            raise ValidationError("You have to be a HR responsible to approve this request.")
        self._create_attendance_records()
        self.write({'state': 'hr_approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_cancel(self):
        # Delete associated attendance records upon cancellation
        self.env['hr.attendance'].search([('mission_id', 'in', self.ids)]).unlink()
        self.write({'state': 'cancelled'})

    def _create_attendance_records(self):
        vals_list = []
        for record in self:
            current_date = record.start_date
            while current_date <= record.end_date:
                vals = record._get_shift_start_end(current_date)
                if vals:
                    vals_list.append(vals)
                current_date += timedelta(days=1)
        if not vals_list:
            raise ValidationError("No attendance shifts found for the mission period. Please ensure attendance shifts are recorded before approving the mission.")
        self.env['hr.attendance'].create(vals_list)

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
