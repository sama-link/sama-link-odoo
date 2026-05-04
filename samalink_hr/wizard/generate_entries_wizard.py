from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class GenerateEntriesWizard(models.TransientModel):
    _name = 'hr.generate.entries.wizard'
    _description = 'Generate Absence & Work Entries'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Leave empty to generate for all employees with active contracts.',
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
    generate_absent_entries = fields.Boolean(
        string='Generate Absence Entries',
        default=True,
        help='Generate absence entries for the selected period and employees.',
    )
    adjust_work_entries = fields.Boolean(
        string='Adjust Work Entries (Flexible Rest Days)',
        default=True,
        help='Adjust work entries for employees on flexible rest day schedules '
             '(convert REST100 to WORK100 for attended days).',
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_("'From' date must be earlier than 'To' date."))

    def _get_target_employees(self):
        """Return selected employees, or all with active contracts if none selected."""
        if self.employee_ids:
            return self.employee_ids
        return self.env['hr.employee'].search([
            ('contract_id', '!=', False),
            ('contract_id.state', '=', 'open'),
        ])

    def action_generate(self):
        """Main action: generate absence entries and/or adjust work entries."""
        self.ensure_one()
        employees = self._get_target_employees()

        if self.generate_absent_entries and employees:
            employees.action_generate_absent_entries(self.date_from, self.date_to)

        if self.adjust_work_entries:
            self.env['hr.work.entry'].action_adjust_flexible_rest_days(
                self.date_from, self.date_to,
                employee_ids=self.employee_ids or None,
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Success"),
                'type': 'success',
                'message': _("Entries generated successfully for %d employee(s).") % len(employees),
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
