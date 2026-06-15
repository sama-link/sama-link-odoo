from odoo import models, fields, api, _


class SlBonusEvaluationException(models.Model):
    """Employees that must SKIP the appraisal/evaluation factor in bonus calc.

    Some employees never receive an appraisal, so their evaluation % would read
    0 and zero out their whole bonus. Listing them here makes the calculator
    treat their evaluation as 100% (i.e. the evaluation factor is skipped) — the
    bonus formulas themselves are unchanged.
    """
    _name = 'sl.bonus.evaluation.exception'
    _description = 'Bonus Evaluation Exception (skip appraisal %)'
    _order = 'employee_id'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade',
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
