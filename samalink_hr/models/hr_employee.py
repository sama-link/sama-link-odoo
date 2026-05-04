from collections import defaultdict
import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    allow_check_from_odoo = fields.Boolean(string="Allow Check From Odoo", default=False, groups="base.group_system,hr.group_hr_user")
    medical_insurance = fields.Selection(related='contract_id.medical_insurance', string="Medical Insurance", readonly=True)

    @api.constrains('pin')
    def _check_pin(self):
        groups = self.read_group(
            domain=[('pin', '!=', False)],
            fields=['pin'],
            groupby=['pin']
        )
        for group in groups:
            if group['pin_count'] > 1:
                raise UserError(f"PIN Code {group['pin']} must be unique found {group['pin_count']} instances.")

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if not (self.env.user.has_group('hr.group_hr_manager') or self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer')):
            raise UserError("You cannot change the Manager field. Please contact your administrator.")

    def _attendance_action_change(self, geo_information=None):
        self.ensure_one()
        if not self.sudo().allow_check_from_odoo:
            raise UserError("You are not allowed to check in/out from Odoo. Please contact your administrator.")
        if not geo_information['latitude'] or not geo_information['longitude']:
            raise UserError("Location information is required for attendance actions.")
        return super()._attendance_action_change(geo_information=geo_information)

    def action_create_user(self):
        self.ensure_one()
        if self.user_id:
            raise ValidationError(_("This employee already has an user."))
        if not self.work_email and not self.mobile_phone:
            raise ValidationError(_("Employee must have a work email to create a user."))
        vals = {
            'create_employee_id': self.id,
            'name': self.name,
            'phone': self.work_phone,
            'mobile': self.mobile_phone,
            'login': self.work_email,
            'partner_id': self.work_contact_id.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id, self.env.ref('samalink_security_groups.group_samalink_employee').id])],
            'password': "1",
        }
        user = self.env['res.users'].sudo().create(vals)

    def action_generate_absent_entries(self, start_date=None, end_date=None):
        if not start_date or not end_date:
            start_date = fields.Date.today().replace(day=1)
            end_date = fields.Date.today()
        self._unlink_existing_absent_entry(start_date, end_date)
        grouped_attendance_dates = self._get_grouped_attendance_dates(start_date, end_date)
        grouped_timeoff_dates = self._get_grouped_timeoff_dates(start_date, end_date)
        public_holidays = self._get_public_holiday_dates(start_date, end_date)
        vals_list = []
        for employee in self:
            contract = employee.contract_id
            calendar = contract.resource_calendar_id if contract else False
            is_flexible = calendar and calendar.flexible_rest_day
            employee_attendance_dates = set(grouped_attendance_dates.get(employee.id, []))
            employee_timeoff_dates = set(grouped_timeoff_dates.get(employee.id, []))
            schedule_rest_days = self._get_schedule_rest_weekdays(calendar) if calendar and not is_flexible else set()

            # Collect all non-attended days in the period
            non_attended_days = []
            current_date = start_date
            while current_date <= end_date:
                if current_date not in employee_attendance_dates:
                    non_attended_days.append(current_date)
                current_date += timedelta(days=1)

            if is_flexible:
                # Flexible rest day logic:
                # Default rest days are Friday (1) or Friday+Saturday (2)
                rest_per_week = int(calendar.rest_days_per_week or '1')
                default_rest_weekdays = {4}  # Friday
                if rest_per_week == 2:
                    default_rest_weekdays.add(5)  # Saturday

                real_absence_dates = self._compute_flexible_absences(
                    employee, employee_attendance_dates, employee_timeoff_dates,
                    public_holidays, default_rest_weekdays, non_attended_days,
                    start_date, end_date,
                )
            else:
                # Non-flexible: standard filtering
                real_absence_dates = []
                for day in non_attended_days:
                    if day in public_holidays:
                        continue
                    if day in employee_timeoff_dates:
                        continue
                    if day.weekday() in schedule_rest_days:
                        continue
                    real_absence_dates.append(day)

            for day in real_absence_dates:
                vals_list.append({
                    'employee_id': employee.id,
                    'date': day,
                    'reason': 'Generated absent entry',
                })

        if vals_list:
            self.env['hr.absent.entry'].create(vals_list)

    def _compute_flexible_absences(self, employee, attendance_dates, timeoff_dates,
                                    public_holidays, default_rest_weekdays,
                                    non_attended_days, start_date, end_date):
        """Compute real absence dates for flexible rest day schedules.

        Logic per Fri→Thu week:
        1. Default rest day (Fri / Sat) not worked → rest day (skip)
        2. Default rest day worked → earns a compensation credit
        3. Each credit covers one non-attended weekday in the same week (earliest first)
        4. Non-attended days covered by credits → compensated rest (skip)
        5. Days with time-off or public holidays → skip
        6. Remaining non-attended days → real absence
        """
        # Group non-attended days by Fri→Thu week
        weeks = defaultdict(list)
        for day in non_attended_days:
            week_key = self._get_friday_week_key(day)
            weeks[week_key].append(day)

        # Count Friday/Saturday credits per week (days employee worked on default rest days)
        week_credits = defaultdict(int)
        all_dates_in_range = set()
        cursor = start_date
        while cursor <= end_date:
            all_dates_in_range.add(cursor)
            cursor += timedelta(days=1)

        # Also look at the anchor week before start_date for cross-month boundary
        anchor_from = self._get_friday_week_key(start_date)
        cursor = anchor_from
        while cursor <= end_date:
            if cursor.weekday() in default_rest_weekdays and cursor in attendance_dates:
                week_key = self._get_friday_week_key(cursor)
                week_credits[week_key] += 1
            cursor += timedelta(days=1)

        real_absences = []
        for day in non_attended_days:
            # Skip public holidays
            if day in public_holidays:
                continue
            # Skip time-off days
            if day in timeoff_dates:
                continue
            # Skip default rest days that were NOT worked (they are actual rest)
            if day.weekday() in default_rest_weekdays:
                continue
            # This is a non-attended work day — check if it can be compensated
            week_key = self._get_friday_week_key(day)
            if week_credits.get(week_key, 0) > 0:
                week_credits[week_key] -= 1  # Use a credit
                continue
            # No credit available → real absence
            real_absences.append(day)

        return real_absences

    @staticmethod
    def _get_friday_week_key(day):
        """Return the anchor Friday date for a Friday→Thursday payroll week."""
        offset = (day.weekday() - 4) % 7
        return day - timedelta(days=offset)

    def _get_grouped_attendance_dates(self, date_from, date_to):
        date_midnight = datetime.combine(date_from, time.min)
        end_of_date = datetime.combine(date_to, time.max)
        domain = [
            ('employee_id', 'in', self.ids),
            ('check_in', '>=', date_midnight),
            ('check_in', '<=', end_of_date)
        ]
        attendance_records = self.env['hr.attendance'].search(domain)
        grouped_attendance = attendance_records.grouped('employee_id')
        attendance_mapped = defaultdict(list)
        for employee, attendance in grouped_attendance.items():
            attendance_mapped[employee.id] = [date_time.date() for date_time in attendance.mapped('check_in')]
        return attendance_mapped

    def _get_grouped_timeoff_dates(self, date_from, date_to):
        """Get approved time-off dates per employee."""
        from_dt = datetime.combine(date_from, time.min)
        to_dt = datetime.combine(date_to, time.max)
        approved_leaves = self.env['hr.leave'].search([
            ('employee_id', 'in', self.ids),
            ('state', '=', 'validate'),
            ('date_from', '<=', to_dt),
            ('date_to', '>=', from_dt),
        ])
        timeoff_mapped = defaultdict(set)
        for leave in approved_leaves:
            start_day = max(leave.date_from.date(), date_from)
            end_day = min(leave.date_to.date(), date_to)
            cursor = start_day
            while cursor <= end_day:
                timeoff_mapped[leave.employee_id.id].add(cursor)
                cursor += timedelta(days=1)
        return timeoff_mapped

    def _get_public_holiday_dates(self, date_from, date_to):
        """Get public holiday dates from resource.calendar.leaves (global leaves)."""
        global_leaves = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),  # Global leaves only
            ('date_from', '<=', datetime.combine(date_to, time.max)),
            ('date_to', '>=', datetime.combine(date_from, time.min)),
        ])
        holidays = set()
        for leave in global_leaves:
            start_day = max(leave.date_from.date(), date_from)
            end_day = min(leave.date_to.date(), date_to)
            cursor = start_day
            while cursor <= end_day:
                holidays.add(cursor)
                cursor += timedelta(days=1)
        return holidays

    def _get_schedule_rest_weekdays(self, calendar):
        """Get weekday numbers (0=Mon, 6=Sun) that are rest days in the schedule.
        A weekday is a rest day if it has NO attendance lines in the calendar.
        """
        if not calendar:
            return set()
        all_weekdays = {0, 1, 2, 3, 4, 5, 6}
        work_weekdays = set()
        for line in calendar.attendance_ids:
            work_weekdays.add(int(line.dayofweek))
        return all_weekdays - work_weekdays

    def _unlink_existing_absent_entry(self, date_from, date_to):
        absent_entries = self.env['hr.absent.entry'].search([
            ('employee_id', 'in', self.ids),
            ('date', '>=', date_from),
            ('date', '<=', date_to)
        ])
        absent_entries.sudo().unlink()

    @api.model
    def cron_generate_absent_entries(self):
        """Scheduled action: generate absence entries for the current week (last 7 days)."""
        today = fields.Date.today()
        # Generate for the past week (7 days ending today)
        start_date = today - timedelta(days=6)
        end_date = today
        employees = self.search([
            ('contract_id', '!=', False),
            ('contract_id.state', '=', 'open'),
        ])
        if employees:
            employees.action_generate_absent_entries(start_date, end_date)
    
    def action_view_absent_entries(self):
        self.ensure_one()
        action = self.env.ref('samalink_hr.action_hr_absent_entry').read()[0]
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_add_data_from_job_position(self):
        self.ensure_one()
        if not self.job_id:
            raise UserError(f"This employee {self.name} does not have a job position assigned.")
        job = self.job_id
        existing_resume_lines = self.resume_line_ids.filtered(lambda line: line.name == job.name)
        vals = {}
        if not existing_resume_lines:
            resume_line_ids = Command.create({
                'name': job.name,
                'date_start': fields.Date.today(),
                'date_end': fields.Date.today(),
                'description': job.description,
            })

            vals.update({
                'resume_line_ids': [resume_line_ids],
            })
        existing_employee_skills = self.employee_skill_ids.mapped('skill_id')
        job_skills_to_add = job.skill_ids.filtered(lambda skill: skill not in existing_employee_skills)
        for skill in job_skills_to_add:
            skill_type_id = skill.skill_type_id
            default_skill_level = skill_type_id.skill_level_ids.filtered(lambda level: level.default_level)
            if default_skill_level:
                vals.setdefault('employee_skill_ids', []).append(Command.create({
                    'skill_id': skill.id,
                    'skill_level_id': default_skill_level.id,
                    'skill_type_id': skill_type_id.id,
                }))
        self.write(vals)

    def action_bulk_add_data_from_job_position(self):
        for employee in self:
            employee.action_add_data_from_job_position()

    def write(self, vals):
        if 'active' in vals and not vals['active']:
            if 'hr.loan' in self.env.registry.models:
                for employee in self:
                    pending_loans = self.env['hr.loan'].search_count([
                        ('employee_id', '=', employee.id),
                        '|',
                        ('state', 'in', ['draft', 'waiting_approval_1']),
                        '&',
                        ('state', '=', 'approve'),
                        ('balance_amount', '>', 0),
                    ])
                    if pending_loans:
                        raise ValidationError(
                            _("Cannot archive employee! The employee has %s unpaid or pending loan(s).") % pending_loans
                        )
        return super(HrEmployee, self).write(vals)
