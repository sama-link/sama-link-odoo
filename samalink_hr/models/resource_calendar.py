from odoo import models, fields, api, _


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    flexible_rest_day = fields.Boolean(
        string='Flexible Rest Days',
        default=False,
        help='When enabled, all days are treated as attendance days. '
             'Employees can choose which day(s) to rest each week. '
             'Default rest days are Friday (1 day) or Friday + Saturday (2 days).'
    )
    rest_days_per_week = fields.Selection(
        [('1', '1 Rest Day (Friday)'), ('2', '2 Rest Days (Friday + Saturday)')],
        string='Rest Days per Week',
        default='1',
        help='Number of rest days per week.\n'
             '1 = Friday is the default rest day.\n'
             '2 = Friday + Saturday are the default rest days.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        calendars = super().create(vals_list)
        for calendar in calendars:
            if calendar.flexible_rest_day:
                calendar._samalink_apply_flexible_full_week_attendance()
        return calendars

    def write(self, vals):
        res = super().write(vals)
        if vals.get('flexible_rest_day'):
            self.filtered(lambda c: c.flexible_rest_day)._samalink_apply_flexible_full_week_attendance()
        return res

    @api.onchange('flexible_rest_day')
    def _onchange_flexible_rest_day(self):
        """When flexible rest day is enabled, set all attendance lines to attendance type."""
        if self.flexible_rest_day:
            attendance_type = self.env.ref(
                'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
            )
            if attendance_type:
                for line in self.attendance_ids:
                    if not line.display_type:
                        line.work_entry_type_id = attendance_type.id

    def _samalink_apply_flexible_full_week_attendance(self):
        """Ensure Mon–Sun have attendance lines and all use attendance work entry type."""
        self.ensure_one()
        if not self.flexible_rest_day:
            return
        if self.two_weeks_calendar:
            # Two-week templates are complex; only normalize work entry types on existing lines.
            self._samalink_set_all_lines_attendance_type()
            return

        attendance_type = self.env.ref(
            'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
        )
        if not attendance_type:
            return

        Attendance = self.env['resource.calendar.attendance']
        real_lines = self.attendance_ids.filtered(lambda l: not l.display_type)
        template = real_lines[:1]
        hour_from = template.hour_from if template else 8.0
        hour_to = template.hour_to if template else 17.0
        day_period = template.day_period if template else 'morning'

        dow_labels = {
            '0': _('Monday'),
            '1': _('Tuesday'),
            '2': _('Wednesday'),
            '3': _('Thursday'),
            '4': _('Friday'),
            '5': _('Saturday'),
            '6': _('Sunday'),
        }
        covered = set(real_lines.mapped('dayofweek'))
        for dow in ('0', '1', '2', '3', '4', '5', '6'):
            if dow in covered:
                continue
            label = dow_labels[dow]
            Attendance.create({
                'name': label,
                'dayofweek': dow,
                'hour_from': hour_from,
                'hour_to': hour_to,
                'day_period': day_period,
                'calendar_id': self.id,
                'work_entry_type_id': attendance_type.id,
            })

        real_lines = self.attendance_ids.filtered(lambda l: not l.display_type)
        real_lines.write({'work_entry_type_id': attendance_type.id})

    def _samalink_set_all_lines_attendance_type(self):
        attendance_type = self.env.ref(
            'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
        )
        if not attendance_type:
            return
        real_lines = self.attendance_ids.filtered(lambda l: not l.display_type)
        real_lines.write({'work_entry_type_id': attendance_type.id})
