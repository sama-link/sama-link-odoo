from datetime import date
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class AdjustWorkEntriesWizard(models.TransientModel):
    _name = 'hr.adjust.work.entries.wizard'
    _description = 'Adjust Work Entries (Flexible Rest Days)'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Leave empty to adjust for all employees with active contracts.',
    )
    date_from = fields.Date(
        string='From',
        required=True,
        default=lambda self: fields.Date.to_string(date.today().replace(day=1)),
    )
    date_to = fields.Date(
        string='To',
        required=True,
        default=lambda self: fields.Date.today(),
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_("'From' date must be earlier than 'To' date."))

    def _get_target_employees(self):
        if self.employee_ids:
            return self.employee_ids
        return self.env['hr.employee'].search([
            ('contract_id', '!=', False),
            ('contract_id.state', '=', 'open'),
        ])

    def action_adjust(self):
        self.ensure_one()
        employees = self._get_target_employees()
        self.env['hr.work.entry'].action_adjust_flexible_rest_days(
            self.date_from,
            self.date_to,
            employee_ids=self.employee_ids or None,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'type': 'success',
                'message': _('Work entries adjusted for %d employee(s).') % len(employees),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
