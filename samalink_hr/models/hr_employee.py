from collections import defaultdict
import logging
from datetime import datetime, time, timedelta
import pytz
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def _samalink_get_flexible_rest_employees(self, employees=None):
        """Employees whose open contract work schedule has Flexible Rest Days enabled."""
        domain = [
            ('contract_id', '!=', False),
            ('contract_id.state', '=', 'open'),
            ('contract_id.resource_calendar_id.flexible_rest_day', '=', True),
        ]
        if employees:
            domain = [('id', 'in', employees.ids)] + domain
        return self.search(domain)

    allow_check_from_odoo = fields.Boolean(string="Allow Check From Odoo", default=False, groups="base.group_system,hr.group_hr_user")
    medical_insurance = fields.Selection(related='contract_id.medical_insurance', string="Medical Insurance", readonly=True)

    # hr_skills_slides gates these compute fields to hr.group_hr_user in
    # PYTHON while gating the form nodes to website_slides officer. The view
    # postprocessor synthesizes an ungated helper node for the button's
    # invisible-modifier reference, so any non-HR user opening the employee
    # form crashes with 'has_subscribed_courses field is undefined'. Widen
    # the python groups to all internal users (UI stays officer-gated).
    has_subscribed_courses = fields.Boolean(groups="base.group_user")
    courses_completion_text = fields.Char(groups="base.group_user")

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
        sl_officer = self.env.ref(
            'samalink_security_groups.group_samalink_hr_officer', raise_if_not_found=False
        )
        can_edit_parent = self.env.user.has_group('hr.group_hr_manager') or (
            sl_officer and self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer')
        )
        if not can_edit_parent:
            raise UserError("You cannot change the Manager field. Please contact your administrator.")

    def _attendance_action_change(self, geo_information=None):
        self.ensure_one()
        if not self.sudo().allow_check_from_odoo:
            raise UserError("You are not allowed to check in/out from Odoo. Please contact your administrator.")
        if not geo_information['latitude'] or not geo_information['longitude']:
            raise UserError("Location information is required for attendance actions.")
        return super()._attendance_action_change(geo_information=geo_information)

    def _samalink_new_user_group_ids(self):
        ids = [self.env.ref('base.group_user').id]
        sl_employee = self.env.ref(
            'samalink_security_groups.group_samalink_employee', raise_if_not_found=False
        )
        if sl_employee:
            ids.append(sl_employee.id)
        return ids

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
            'groups_id': [(6, 0, self._samalink_new_user_group_ids())],
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

            if is_flexible:
                real_absence_dates, _rest_taken = employee._samalink_flexible_split_absence_and_rest(
                    start_date, end_date,
                )
            else:
                non_attended_days = []
                current_date = start_date
                while current_date <= end_date:
                    if current_date not in employee_attendance_dates:
                        non_attended_days.append(current_date)
                    current_date += timedelta(days=1)
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

    def _samalink_flexible_calc_start(self, start_date):
        """Attendance/credit window start: previous Fri→Thu week before the period."""
        return self._get_friday_week_key(start_date) - timedelta(days=7)

    def _samalink_flexible_split_absence_and_rest(self, start_date, end_date):
        """Split non-attended days into real absences vs actual rest (flexible schedule only).

        Returns (real_absence_dates_sorted, rest_taken_dates_sorted) for [start_date, end_date].

        Rest taken = default Fri/Sat not worked, or another weekday not worked when covered
        by a compensation credit from working a default rest day (same Fri→Thursday week).
        Public holidays and approved time off are excluded from both lists.

        Week credits include the previous payroll week so period-start days are classified
        correctly (not wrongly marked absent).
        """
        self.ensure_one()
        employee = self
        contract = employee.contract_id
        calendar = contract.resource_calendar_id if contract else False
        if not calendar or not calendar.flexible_rest_day:
            return [], []

        rest_per_week = int(calendar.rest_days_per_week or '1')
        default_rest_weekdays = {4}
        if rest_per_week == 2:
            default_rest_weekdays.add(5)

        calc_start = self._samalink_flexible_calc_start(start_date)
        attendance_dates_period = set(
            self._get_grouped_attendance_dates(start_date, end_date).get(employee.id, [])
        )
        attendance_dates_credit = set(
            self._get_grouped_attendance_dates(calc_start, end_date).get(employee.id, [])
        )
        timeoff_dates = set(
            self._get_grouped_timeoff_dates(start_date, end_date).get(employee.id, set())
        )
        public_holidays = self._get_public_holiday_dates(start_date, end_date)

        non_attended_days = []
        current_date = start_date
        while current_date <= end_date:
            if current_date not in attendance_dates_period:
                non_attended_days.append(current_date)
            current_date += timedelta(days=1)

        week_credits = defaultdict(int)
        cursor = calc_start
        while cursor <= end_date:
            if cursor.weekday() in default_rest_weekdays and cursor in attendance_dates_credit:
                week_key = self._get_friday_week_key(cursor)
                week_credits[week_key] += 1
            cursor += timedelta(days=1)

        real_absences = []
        rest_taken = []
        for day in non_attended_days:
            if day in public_holidays:
                continue
            if day in timeoff_dates:
                continue
            if day.weekday() in default_rest_weekdays:
                rest_taken.append(day)
                continue
            week_key = self._get_friday_week_key(day)
            if week_credits.get(week_key, 0) > 0:
                week_credits[week_key] -= 1
                rest_taken.append(day)
                continue
            real_absences.append(day)

        return sorted(real_absences), sorted(rest_taken)

    def _samalink_default_rest_dates_for_week(self, week_key, rest_per_week):
        """Friday (and Saturday if 2 rest days/week) for a Fri→Thu payroll week."""
        dates = [week_key]
        if int(rest_per_week or '1') == 2:
            dates.append(week_key + timedelta(days=1))
        return dates

    def _samalink_flexible_rest_dates_for_work_entries(self, start_date, end_date):
        """Rest/absence split for work-entry adjust, with default top-up per week.

        If the employee took fewer rest days than entitled in a payroll week,
        the shortfall is filled by injecting the default rest days (Friday first,
        then Saturday for 2-rest schedules).  A default day that falls on a
        public holiday or approved leave is skipped (it's already covered).
        Days that are already in rest_set (from the full-period split) are not
        counted twice.
        """
        self.ensure_one()
        real_abs, rest_taken = self._samalink_flexible_split_absence_and_rest(
            start_date, end_date,
        )
        contract = self.contract_id
        calendar = contract.resource_calendar_id if contract else False
        if not calendar or not calendar.flexible_rest_day:
            return real_abs, rest_taken

        rest_per_week = int(calendar.rest_days_per_week or '1')
        rest_set = set(rest_taken)
        real_set = set(real_abs)

        timeoff_dates = set(
            self._get_grouped_timeoff_dates(start_date, end_date).get(self.id, set())
        )
        public_holidays = self._get_public_holiday_dates(start_date, end_date)

        calc_start = self._samalink_flexible_calc_start(start_date)
        week_key = self._get_friday_week_key(calc_start)
        end_week_key = self._get_friday_week_key(end_date)
        while week_key <= end_week_key:
            week_start = week_key
            week_end = week_key + timedelta(days=6)
            _week_real, week_rest = self._samalink_flexible_split_absence_and_rest(
                week_start, week_end,
            )
            already_in_range = [
                d for d in week_rest
                if start_date <= d <= end_date
            ]
            already_in_rest = [
                d for d in rest_set
                if week_start <= d <= week_end
            ]
            week_count = len(set(already_in_range) | set(already_in_rest))
            needed = rest_per_week - week_count
            if needed > 0:
                for day in self._samalink_default_rest_dates_for_week(
                    week_key, rest_per_week,
                ):
                    if needed <= 0:
                        break
                    if day < start_date or day > end_date:
                        continue
                    if day in public_holidays or day in timeoff_dates:
                        continue
                    if day in rest_set:
                        continue
                    rest_set.add(day)
                    real_set.discard(day)
                    needed -= 1
                    _logger.debug(
                        "Flex rest top-up: emp %s week %s → injected %s (still need %d)",
                        self.id, week_key, day, needed,
                    )
            week_key += timedelta(days=7)

        return sorted(real_set), sorted(rest_set)

    def _samalink_get_actual_rest_dates_flexible(self, start_date, end_date):
        """Dates the employee actually rested (flexible rules), excluding holidays and leave."""
        _real, rest_taken = self._samalink_flexible_split_absence_and_rest(start_date, end_date)
        return rest_taken

    @staticmethod
    def _get_friday_week_key(day):
        """Return the anchor Friday date for a Friday→Thursday payroll week."""
        offset = (day.weekday() - 4) % 7
        return day - timedelta(days=offset)

    def _get_grouped_attendance_dates(self, date_from, date_to):
        cairo_tz = pytz.timezone("Africa/Cairo")
        utc_tz = pytz.timezone("UTC")
        local_start = datetime.combine(date_from, time.min)
        local_end = datetime.combine(date_to, time.max)
        date_midnight = cairo_tz.localize(local_start).astimezone(utc_tz).replace(tzinfo=None)
        end_of_date = cairo_tz.localize(local_end).astimezone(utc_tz).replace(tzinfo=None)
        domain = [
            ('employee_id', 'in', self.ids),
            ('check_in', '>=', date_midnight),
            ('check_in', '<=', end_of_date)
        ]
        attendance_records = self.env['hr.attendance'].search(domain)
        grouped_attendance = attendance_records.grouped('employee_id')
        attendance_mapped = defaultdict(list)
        for employee, attendance in grouped_attendance.items():
            attendance_mapped[employee.id] = [
                utc_tz.localize(date_time).astimezone(cairo_tz).date()
                for date_time in attendance.mapped('check_in')
            ]
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

    @staticmethod
    def _is_rest_work_entry_type(work_entry_type):
        """True when the calendar line work entry type represents a rest day."""
        if not work_entry_type:
            return False
        code = (work_entry_type.code or '').upper()
        if code in ('REST100', 'REST'):
            return True
        name = (work_entry_type.name or '').lower()
        return 'rest' in name

    def _get_schedule_rest_weekdays(self, calendar):
        """Weekdays (0=Mon … 6=Sun) that are rest days on the working schedule.

        A weekday is rest when it has no calendar line, or only lines whose work
        entry type is Rest (e.g. REST100 / "Rest Day"). Days with at least one
        Attendance/WORK line are working days.
        """
        if not calendar:
            return set()
        all_weekdays = {0, 1, 2, 3, 4, 5, 6}
        work_weekdays = set()
        for line in calendar.attendance_ids.filtered(lambda l: not l.display_type):
            if not self._is_rest_work_entry_type(line.work_entry_type_id):
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

    def _get_skill_level_for_job_skill(self, skill):
        """Default level for a job skill, or the first configured level."""
        skill_levels = skill.skill_type_id.skill_level_ids
        if not skill_levels:
            return self.env['hr.skill.level']
        return skill_levels.filtered('default_level')[:1] or skill_levels.sorted('level_progress')[:1]

    def _add_job_skills_to_employee(self, skills):
        """Add job skills to the employee card without removing existing ones."""
        self.ensure_one()
        existing_skill_ids = set(self.employee_skill_ids.mapped('skill_id').ids)
        commands = []
        skipped = []
        for skill in skills:
            if skill.id in existing_skill_ids:
                continue
            level = self._get_skill_level_for_job_skill(skill)
            if not level:
                skipped.append(skill.display_name)
                continue
            commands.append(Command.create({
                'skill_id': skill.id,
                'skill_level_id': level.id,
                'skill_type_id': skill.skill_type_id.id,
            }))
        if commands:
            self.write({'employee_skill_ids': commands})
        return skipped

    def action_add_data_from_job_position(self):
        self.ensure_one()
        if not self.job_id:
            raise UserError(_("This employee %s does not have a job position assigned.") % self.name)
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
        job_skill_ids = set(job.skill_ids.ids)
        skills_to_remove = self.employee_skill_ids.filtered(
            lambda es: es.skill_id.id not in job_skill_ids
        )
        if skills_to_remove:
            skills_to_remove.unlink()

        skipped = self._add_job_skills_to_employee(job.skill_ids)
        if vals:
            self.write(vals)
        if skipped:
            raise UserError(_(
                "Some job skills could not be added because their skill type has no levels configured:\n%s"
            ) % '\n'.join(f"- {name}" for name in skipped))

    def action_bulk_add_data_from_job_position(self):
        processed = 0
        skipped = []
        for employee in self:
            if not employee.job_id:
                skipped.append(_('%s (no job position)') % employee.name)
                continue
            try:
                employee.action_add_data_from_job_position()
                processed += 1
            except UserError as exc:
                skipped.append('%s: %s' % (employee.name, exc.args[0]))
        message = _('Added job data for %s employee(s).') % processed
        if skipped:
            message += '\n' + _('Skipped: %s') % ', '.join(skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Add Data From Job Position'),
                'type': 'success' if processed else 'warning',
                'message': message,
                'sticky': bool(skipped),
            },
        }

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
