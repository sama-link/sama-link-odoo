from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    friday_swap_excluded_schedule_ids = fields.Many2many(
        'resource.calendar',
        string='Excluded Working Schedules (Friday Swap)',
        help='Employees on these schedules are excluded from Friday swap payroll adjustment.',
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        raw_ids = self.env['ir.config_parameter'].sudo().get_param(
            'samalink_hr.friday_swap_excluded_schedule_ids',
            default='',
        )
        schedule_ids = []
        for value in (raw_ids or '').split(','):
            value = value.strip()
            if value.isdigit():
                schedule_ids.append(int(value))
        res.update(
            friday_swap_excluded_schedule_ids=[(6, 0, schedule_ids)],
        )
        return res

    def set_values(self):
        super().set_values()
        self.ensure_one()
        values = ','.join(str(schedule_id) for schedule_id in self.friday_swap_excluded_schedule_ids.ids)
        self.env['ir.config_parameter'].sudo().set_param(
            'samalink_hr.friday_swap_excluded_schedule_ids',
            values,
        )
        # Keep backward-compatible name parameter as fallback.
        names = ','.join(self.friday_swap_excluded_schedule_ids.mapped('name'))
        self.env['ir.config_parameter'].sudo().set_param(
            'samalink_hr.friday_swap_excluded_schedule_names',
            names,
        )
