"""Wizard: warn about employees with no active contract in the batch period.

Opened by ``hr.appraisal.batch.employees.action_generate_appraisals`` when
some of the selected employees have no open/closed contract overlapping the
batch's Period From → Period To. Employees WITH a valid contract are carried
in ``ok_employee_ids`` and always generated; each employee WITHOUT one gets
a line with an include/exclude radio (default: include) so HR explicitly
decides who still enters the appraisal batch.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class HrAppraisalBatchContractWarning(models.TransientModel):
    _name = 'hr.appraisal.batch.contract.warning'
    _description = 'Employees Without Active Contract In Period'

    batch_id = fields.Many2one(
        'hr.appraisal.batch', string='Batch', required=True, ondelete='cascade',
    )
    date_from = fields.Date(related='batch_id.date_from', readonly=True)
    date_to = fields.Date(related='batch_id.date_to', readonly=True)
    ok_employee_ids = fields.Many2many(
        'hr.employee',
        'hr_appraisal_contract_warn_ok_rel', 'wizard_id', 'employee_id',
        string='Employees With Contract',
        help='Selected employees that DO have a contract covering the period '
             '— they are always generated when confirming.',
    )
    line_ids = fields.One2many(
        'hr.appraisal.batch.contract.warning.line', 'wizard_id',
        string='Employees Without Contract',
    )

    def action_confirm(self):
        self.ensure_one()
        batch = self.batch_id
        batch._assert_can_generate_appraisals()
        included = self.line_ids.filtered(
            lambda l: l.decision == 'include'
        ).mapped('employee_id')
        employees = self.ok_employee_ids | included
        # Re-filter duplicates defensively (another user may have generated
        # appraisals between the two wizard steps).
        employees -= batch.appraisal_ids.mapped('employee_id')
        if not employees:
            raise UserError(_(
                "No employees left to generate — everyone was either "
                "excluded or already has an appraisal in this batch."
            ))
        batch._generate_appraisals_for_employees(employees)
        excluded = self.line_ids.filtered(lambda l: l.decision == 'exclude')
        if excluded:
            # Plain text — message_post escapes HTML in interpolated bodies.
            batch.message_post(body=_(
                "Skipped %(count)s employee(s) without an active contract in "
                "the period %(date_from)s → %(date_to)s: %(names)s"
            ) % {
                'count': len(excluded),
                'date_from': batch.date_from,
                'date_to': batch.date_to,
                'names': "، ".join(excluded.mapped('employee_id.name')),
            })
        return {'type': 'ir.actions.act_window_close'}


class HrAppraisalBatchContractWarningLine(models.TransientModel):
    _name = 'hr.appraisal.batch.contract.warning.line'
    _description = 'Employee Without Active Contract In Period'
    _order = 'id'

    wizard_id = fields.Many2one(
        'hr.appraisal.batch.contract.warning', required=True, ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, readonly=True,
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', string='Job Position', readonly=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Department', readonly=True,
    )
    decision = fields.Selection([
        ('include', 'Add to Batch'),
        ('exclude', "Don't Add"),
    ], string='Decision', default='include', required=True)
