from odoo import models, fields, _
from odoo.exceptions import UserError, ValidationError

class HrContractInherit(models.Model):
    _inherit = 'hr.contract'

    salary_payment_method = fields.Selection([
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('other', 'Other')
    ], string="Salary Payment Method", default='bank_transfer', required=True)
    not_listed_payment_method = fields.Char(string="If Other, specify")
    work_location_id = fields.Many2one(related="employee_id.work_location_id", domain="[('address_id', '=', address_id)]")
    medical_insurance = fields.Selection([
        ('sama_link_heliopolis', '1- سما لينك للتجاره والتصنيع (مصر الجديده)'),
        ('sama_link_downtown', '2-سما لينك للتجاره والتصنيع (وسط البلد)'),
        ('sama_tech_downtown', '3-سما تكنولوجي الحسن على محمد (وسط البلد)'),
        ('sama_tech_hadayek', '4-سما تكنولوجي الحسن على محمد (حدائق القبة)')
    ], string="Medical Insurance")
    _SCHEDULE_CONFLICT_MSG = "Changing the contract on this employee changes their working schedule"

    def write(self, vals):
        is_archiving = ('active' in vals and not vals['active'])
        is_closing = ('state' in vals and vals['state'] in ['close', 'cancel'])
        if is_archiving or is_closing:
            # Block if employee has unpaid/active loans (same idea as custody blocking).
            if 'hr.loan' in self.env.registry.models:
                for contract in self:
                    if not contract.employee_id:
                        continue
                    pending_loans = self.env['hr.loan'].search_count([
                        ('employee_id', '=', contract.employee_id.id),
                        '|',
                        ('state', 'in', ['draft', 'waiting_approval_1']),
                        '&',
                        ('state', '=', 'approve'),
                        ('balance_amount', '>', 0),
                    ])
                    if pending_loans:
                        raise ValidationError(
                            _("Cannot close or archive contract! The employee has %s unpaid or pending loan(s).") % pending_loans
                        )

        if is_archiving:
            if (not self.env.user.has_group('base.group_system')
                    and not self.env.user.has_group('hr.group_hr_manager')):
                raise UserError(_("Only Administrators can archive contracts."))
        try:
            return super(HrContractInherit, self).write(vals)
        except (ValidationError, UserError) as err:
            # Force-skip the specific working schedule/leave consistency blocker.
            if not vals.get('resource_calendar_id') or self._SCHEDULE_CONFLICT_MSG not in str(err):
                raise

            fallback_vals = dict(vals)
            forced_calendar_id = fallback_vals.pop('resource_calendar_id')
            if fallback_vals:
                super(HrContractInherit, self).write(fallback_vals)

            self.env.cr.execute(
                """
                UPDATE hr_contract
                   SET resource_calendar_id = %s,
                       write_uid = %s,
                       write_date = NOW()
                 WHERE id IN %s
                """,
                (forced_calendar_id, self.env.uid, tuple(self.ids)),
            )
            self.invalidate_recordset()
            return True
