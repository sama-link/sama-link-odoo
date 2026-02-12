from datetime import date, timedelta
from odoo import models, fields, api, _


PERIOD_MAP = {
    'today': 0,
    'yesterday': -1,
}

class ZKAttendancePeriodWizard(models.TransientModel):
    _name = 'zk.attendance.period.wizard'
    _description = 'ZK Attendance Period Wizard'

    date_period = fields.Selection([
        ('custom', 'User Defined'),
        ('today', 'Today'),
        ('yesterday', 'Yesterday'),
        ('last_week', 'Last Week'),
        ('this_week', 'This Week'),
        ('last_month', 'Last Month'),
        ('this_month', 'This Month'),
    ], string='Date Period', default='today', required=True)

    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    department_ids = fields.Many2many(
        'zk.department',
        string='Departments'
    )
    employee_ids = fields.Many2many(
        'zk.employee',
        string='Employees'
    )
    create_hr_attendance = fields.Boolean(
        string='Create HR Attendance',
        default=False
    )

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for wizard in self:
            if wizard.start_date > wizard.end_date:
                raise ValidationError("Start Date must be before End Date.")

    @api.onchange('date_period')
    def _onchange_date_period(self):
        today = date.today()
        if self.date_period in PERIOD_MAP:
            days_offset = PERIOD_MAP[self.date_period]
            self.start_date = today + timedelta(days=days_offset)
            self.end_date = today + timedelta(days=days_offset)
        elif self.date_period == 'last_week':
            self.start_date = today + timedelta(days=-13)
            self.end_date = today + timedelta(days=-7)
        elif self.date_period == 'this_week':
            self.start_date = today + timedelta(days=-6)
            self.end_date = today
        elif self.date_period == 'last_month':
            last_day_of_last_month = today.replace(day=1) - timedelta(days=1)
            self.start_date = last_day_of_last_month.replace(day=1)
            self.end_date = last_day_of_last_month
        elif self.date_period == 'this_month':
            self.start_date = today.replace(day=1)
            self.end_date = today

    def do_action(self):
        zk_api_id = self.env.context.get('active_id')
        zk_api = self.env['zk.api'].browse(zk_api_id)
        zk_api.action_sync_attendance(
            start_date=self.start_date,
            end_date=self.end_date,
            departments=self.department_ids,
            employees=self.employee_ids,
            cron=True
        )
        if self.create_hr_attendance:
            attendance_ids = self.env['zk.attendance'].search([
                ('att_date', '>=', self.start_date),
                ('att_date', '<=', self.end_date)
            ])
            attendance_ids.action_link_hr_attendance()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Attendance synchronized successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }

