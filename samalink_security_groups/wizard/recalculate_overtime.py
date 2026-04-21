import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RecalculateOvertimeWizard(models.TransientModel):
    _name = 'recalculate.overtime.wizard'
    _description = 'Recalculate Overtime Wizard'

    selected_count = fields.Integer(string='Selected Records', readonly=True)
    approved_count = fields.Integer(string='Approved in Selection', readonly=True)
    refused_count = fields.Integer(string='Refused in Selection', readonly=True)

    force_update_approved = fields.Boolean(
        string="Force update 'Extra Hours' on Approved records",
        help="If enabled, the validated 'Extra Hours' of records currently in "
             "Approved status will also be refreshed to match the newly "
             "computed overtime. Otherwise, their existing validated value is kept.",
    )
    reset_refused_to_approve = fields.Boolean(
        string="Reset Refused records to 'To Approve'",
        help="If enabled, selected records with Refused status will be moved "
             "back to 'To Approve' so the freshly computed overtime is applied "
             "and can be re-validated. Otherwise, they stay Refused with 0 Extra Hours.",
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        attendances = self._get_selected_attendances()
        defaults['selected_count'] = len(attendances)
        defaults['approved_count'] = len(attendances.filtered(lambda a: a.overtime_status == 'approved'))
        defaults['refused_count'] = len(attendances.filtered(lambda a: a.overtime_status == 'refused'))
        return defaults

    @api.model
    def _get_selected_attendances(self):
        active_ids = self.env.context.get('active_ids', [])
        return self.env['hr.attendance'].sudo().browse(active_ids).exists()

    def action_recalculate(self):
        self.ensure_one()
        attendances = self._get_selected_attendances()
        if not attendances:
            raise UserError(_("Please select attendance records from the list first."))

        # 1) Optionally flip Refused -> To Approve BEFORE the recompute, so the
        #    stock compute of validated_overtime_hours picks up the new overtime.
        refused_records = attendances.filtered(lambda a: a.overtime_status == 'refused')
        flipped_refused = 0
        if self.reset_refused_to_approve and refused_records:
            refused_records.write({'overtime_status': 'to_approve'})
            flipped_refused = len(refused_records)

        # 2) Apply custom rule per selected attendance:
        #    Extra Hours = worked_hours - Average Hour per Day (calendar.hours_per_day)
        updated_count = 0
        approved_updated = 0
        for att in attendances:
            calendar = att.employee_id.resource_calendar_id or att.employee_id.company_id.resource_calendar_id
            average_hours_per_day = calendar.hours_per_day if calendar else 0.0
            overtime_value = att.worked_hours - average_hours_per_day
            if overtime_value < 0.75:
                overtime_value = 0.0

            values = {'overtime_hours': overtime_value}

            # Keep stock semantics unless user asks otherwise:
            # - to_approve: validated follows overtime
            # - refused: stays 0 unless moved back to to_approve
            # - approved: only refreshed when force checkbox is on
            if att.overtime_status == 'to_approve':
                values['validated_overtime_hours'] = overtime_value
            elif att.overtime_status == 'approved' and self.force_update_approved:
                values['validated_overtime_hours'] = overtime_value
                approved_updated += 1

            att.write(values)
            updated_count += 1

        employees_touched = len(attendances.mapped('employee_id'))

        message = _(
            "Recalculated overtime for %(att)d attendance(s) for %(emps)d employee(s) "
            "using: worked hours - Average Hour per Day."
        ) % {'att': updated_count, 'emps': employees_touched}
        if flipped_refused:
            message += "\n" + (_("%d refused record(s) moved back to 'To Approve'.") % flipped_refused)
        if approved_updated:
            message += "\n" + (_("%d approved record(s) had their Extra Hours refreshed.") % approved_updated)

        _logger.info(message)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Overtime Recalculated'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
