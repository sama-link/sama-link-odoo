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

        # 2) Recompute the daily hr.attendance.overtime reservoir against the
        #    current working schedule, then queue recompute of overtime_hours /
        #    validated_overtime_hours / expected_hours on all same-day siblings.
        attendance_dates = attendances._get_attendances_dates()
        attendances._update_overtime(employee_attendance_dates=attendance_dates)

        # 3) Materialize queued computes so we can read fresh values below.
        self.env.flush_all()

        # 4) Optionally force-refresh validated_overtime_hours on records still
        #    in Approved status (stock compute skips them to preserve manual edits).
        approved_updated = 0
        if self.force_update_approved:
            approved_records = attendances.filtered(lambda a: a.overtime_status == 'approved')
            for att in approved_records:
                if att.validated_overtime_hours != att.overtime_hours:
                    att.validated_overtime_hours = att.overtime_hours
                    approved_updated += 1

        days_touched = len({d for dates in attendance_dates.values() for _, d in dates})
        employees_touched = len(attendance_dates)

        message = _(
            "Recalculated overtime for %(att)d attendance(s) across "
            "%(days)d day(s) for %(emps)d employee(s)."
        ) % {'att': len(attendances), 'days': days_touched, 'emps': employees_touched}
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
