from datetime import datetime, time, timedelta
from odoo import models, fields, api


class HrAbsentEntry(models.Model):
    _name = 'hr.absent.entry'
    _description = 'HR Absent Entry'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    leave_entry_id = fields.Many2one(
        'hr.work.entry',
        compute='_compute_leave_entry_id',
        store=True,
        string='Timeoff Entry',
        help='Link to the work entry associated with this absent record.',
    )
    date = fields.Date(string='Absent Date', required=True)
    reason = fields.Text(string='Reason')

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s: %s' % (record.employee_id.name, record.date)

    @api.depends('date')
    def _compute_leave_entry_id(self):
        attendance_type = self.env.ref('hr_work_entry.work_entry_type_attendance')
        for record in self:
            date = record.date
            date_midnight = datetime.combine(date, time.min)
            end_of_date = datetime.combine(date, time.max)
            work_entries = self.env['hr.work.entry'].search([
                ('employee_id', '=', record.employee_id.id),
                ('date_start', '>=', date_midnight),
                ('date_stop', '<=', end_of_date),
                ('work_entry_type_id', '!=', attendance_type.id),
                ('work_entry_type_id.code', '!=', 'LATE')
            ], limit=1)
            record.leave_entry_id = work_entries.id