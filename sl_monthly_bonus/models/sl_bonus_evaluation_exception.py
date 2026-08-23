from odoo import models, fields, api, _


class SlBonusEvaluationException(models.Model):
    """Employees that must SKIP the appraisal/evaluation factor in bonus calc.

    Some employees never receive an appraisal, so their evaluation % would read
    0 and zero out their whole bonus. Listing them here makes the calculator
    treat their evaluation as 100% (i.e. the evaluation factor is skipped) — the
    bonus formulas themselves are unchanged.

    The list is mirrored on the employee card (Appraisal & Bonus tab →
    "Bonus Evaluation" = Fixed) and the two are kept in sync both ways.
    """
    _name = 'sl.bonus.evaluation.exception'
    _description = 'Bonus Evaluation Exception (skip appraisal %)'
    _order = 'employee_id'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade',
        # Only employees who can take a bonus at all (employee card →
        # Appraisal & Bonus tab → "Bonus" checked) belong on this list.
        domain="[('bonus_eligible', '=', True)]",
    )
    reason = fields.Char(string='Reason')

    _sql_constraints = [
        ('uniq_employee',
         'unique(employee_id)',
         'This employee is already in the evaluation exception list.'),
    ]

    @api.depends('employee_id')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.employee_id.name or ''

    @api.model
    def is_exempt(self, employee):
        """True if the employee should skip the evaluation factor."""
        emp_id = employee.id if hasattr(employee, 'id') else employee
        if not emp_id:
            return False
        return bool(self.sudo().search_count([('employee_id', '=', emp_id)]))

    def _sync_employee_card(self, employees, listed):
        """Reverse sync: keep the employee card's "Bonus Evaluation" select
        in step with this list. Adding an employee here checks the "Bonus"
        box and selects "Fixed"; removing them reverts the select to
        "Depends on appraisal". The context flag prevents hr.employee from
        syncing straight back into this list."""
        if self.env.context.get('skip_bonus_exception_sync') or not employees:
            return
        employees = employees.sudo().with_context(skip_bonus_exception_sync=True)
        if listed:
            employees.write({
                'bonus_eligible': True,
                'bonus_evaluation_mode': 'fixed',
            })
        else:
            employees.filtered(
                lambda e: e.bonus_evaluation_mode == 'fixed'
            ).write({'bonus_evaluation_mode': 'appraisal'})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_employee_card(records.employee_id, listed=True)
        return records

    def write(self, vals):
        previous = self.employee_id
        res = super().write(vals)
        if 'employee_id' in vals:
            self._sync_employee_card(previous - self.employee_id, listed=False)
            self._sync_employee_card(self.employee_id, listed=True)
        return res

    def unlink(self):
        previous = self.employee_id
        res = super().unlink()
        self._sync_employee_card(previous, listed=False)
        return res
