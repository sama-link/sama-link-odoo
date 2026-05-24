from datetime import date

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class AdjustWorkEntriesWizard(models.TransientModel):
    _name = 'hr.adjust.work.entries.wizard'
    _description = 'Adjust Work Entries (Flexible Rest Days)'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Only employees with Flexible Rest Days on their work schedule are adjusted. '
             'Leave empty to run for all such employees with active contracts.',
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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') != 'hr.work.entry':
            return res
        active_ids = self.env.context.get('active_ids') or []
        if not active_ids:
            return res
        entries = self.env['hr.work.entry'].browse(active_ids)
        employees = entries.mapped('employee_id')
        if 'employee_ids' in fields_list:
            flexible = self.env['hr.employee']._samalink_get_flexible_rest_employees(
                employees,
            )
            res['employee_ids'] = [Command.set(flexible.ids)]
        entry_dates = [entry.date_start.date() for entry in entries if entry.date_start]
        if entry_dates:
            if 'date_from' in fields_list:
                res.setdefault('date_from', min(entry_dates))
            if 'date_to' in fields_list:
                res.setdefault('date_to', max(entry_dates))
        return res

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise ValidationError(_("'From' date must be earlier than 'To' date."))

    def _get_source_employees(self):
        if self.employee_ids:
            return self.employee_ids
        if (
            self.env.context.get('active_model') == 'hr.work.entry'
            and self.env.context.get('active_ids')
        ):
            entries = self.env['hr.work.entry'].browse(self.env.context['active_ids'])
            return entries.mapped('employee_id')
        return self.env['hr.employee'].search([
            ('contract_id', '!=', False),
            ('contract_id.state', '=', 'open'),
        ])

    def _get_target_employees(self):
        return self.env['hr.employee']._samalink_get_flexible_rest_employees(
            self._get_source_employees(),
        )

    def action_adjust(self):
        self.ensure_one()
        source_employees = self._get_source_employees()
        employees = self._get_target_employees()
        if employees:
            self.env['hr.work.entry'].action_adjust_flexible_rest_days(
                self.date_from,
                self.date_to,
                employee_ids=employees,
            )
        skipped = len(source_employees) - len(employees)
        if employees:
            message = _(
                'Work entries adjusted for %d employee(s) with flexible rest schedules.'
            ) % len(employees)
            if skipped:
                message += ' ' + _(
                    '%d employee(s) were skipped (Flexible Rest Days not enabled on their schedule).'
                ) % skipped
            notif_type = 'success'
            title = _('Done')
        else:
            message = _(
                'No work entries were adjusted. Selected employee(s) do not have '
                'Flexible Rest Days enabled on their work schedule.'
            )
            notif_type = 'info'
            title = _('Skipped')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'type': notif_type,
                'message': message,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
