from collections import defaultdict
import logging
from datetime import datetime, time, timedelta
from odoo import models, fields, api, _, Command
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    allow_check_from_odoo = fields.Boolean(string="Allow Check From Odoo", default=False, groups="base.group_system,hr.group_hr_user")

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
        grouped_attendance_dates = self._get_grouped_attendece_dates(start_date, end_date)
        vals_list = []
        for employee in self:
            employee_attendance_dates = grouped_attendance_dates.get(employee.id, [])
            current_date = start_date
            while current_date <= end_date:
                if (current_date not in employee_attendance_dates):
                    vals_list.append({
                        'employee_id': employee.id,
                        'date': current_date,
                        'reason': 'Generated absent entry'
                    })
                current_date += timedelta(days=1)
        if vals_list:
            self.env['hr.absent.entry'].create(vals_list)

    def _get_grouped_attendece_dates(self, date_from, date_to):
        date_midnight = datetime.combine(date_from, time.min)
        end_of_date = datetime.combine(date_to, time.max)
        domain = [('check_in', '>=', date_midnight), ('check_in', '<=', end_of_date)]
        attendance_records = self.env['hr.attendance'].search([
            ('employee_id', 'in', self.ids),
            ('check_in', '>=', date_from),
            ('check_out', '<=', date_to)
        ])
        grouped_attendance = attendance_records.grouped('employee_id')
        attendance_mapped = defaultdict(list)
        for employee, attendance in grouped_attendance.items():
            attendance_mapped[employee.id] = [date_time.date() for date_time in attendance.mapped('check_in')]
        return attendance_mapped

    def _unlink_existing_absent_entry(self, date_from, date_to):
        absent_entries = self.env['hr.absent.entry'].search([
            ('employee_id', 'in', self.ids),
            ('date', '>=', date_from),
            ('date', '<=', date_to)
        ])
        absent_entries.sudo().unlink()
    
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
