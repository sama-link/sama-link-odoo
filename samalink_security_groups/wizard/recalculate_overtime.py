import logging
from datetime import datetime, time
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RecalculateOvertimeWizard(models.TransientModel):
    _name = 'recalculate.overtime.wizard'
    _description = 'Recalculate Overtime Wizard'

    date_from = fields.Date(
        string='Period From',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Period To',
        required=True,
        default=fields.Date.today,
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Leave empty to recalculate for all employees.',
    )
    overtime_status = fields.Selection(
        [
            ('to_approve', 'To Approve'),
            ('approved', 'Approved'),
            ('refused', 'Refused'),
        ],
        string='Overtime Status',
        help='Leave empty to recalculate for all statuses.',
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from > wizard.date_to:
                raise UserError(_("'Period From' must be before or equal to 'Period To'."))

    def action_recalculate(self):
        self.ensure_one()
        from_dt = datetime.combine(self.date_from, time.min)
        to_dt = datetime.combine(self.date_to, time.max)

        domain = [
            ('check_in', '>=', from_dt),
            ('check_in', '<=', to_dt),
        ]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.overtime_status:
            domain.append(('overtime_status', '=', self.overtime_status))

        attendances = self.env['hr.attendance'].sudo().search(domain)
        if not attendances:
            raise UserError(_("No attendance records found matching the selected criteria."))

        _logger.info(
            "Recalculating overtime for %d attendance records (period %s – %s).",
            len(attendances), self.date_from, self.date_to,
        )
        attendances._compute_overtime_hours()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Overtime Recalculated'),
                'message': _('%d attendance record(s) have been recalculated.') % len(attendances),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
