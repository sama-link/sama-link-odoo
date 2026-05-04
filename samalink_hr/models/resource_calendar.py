from odoo import models, fields, api


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

    @api.onchange('flexible_rest_day')
    def _onchange_flexible_rest_day(self):
        """When flexible rest day is enabled, set all attendance lines to attendance type."""
        if self.flexible_rest_day:
            attendance_type = self.env.ref(
                'hr_work_entry.work_entry_type_attendance', raise_if_not_found=False
            )
            if attendance_type:
                for line in self.attendance_ids:
                    line.work_entry_type_id = attendance_type.id
