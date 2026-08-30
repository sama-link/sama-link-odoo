"""Wizard: review employees with issues in the batch period before they
enter an appraisal batch.

Opened from the Generate Appraisals wizard (button "Review employees with
issues", or automatically when selected employees turn out to have issues).
One line per flagged employee, showing why they were flagged:

  * changed job position during the period → HR picks which position the
    appraisal is for (the positions held in the period are offered);
  * a contract starts or ends inside the period → HR decides add / don't add;
  * no running/closed contract overlapping the period → same decision.

Employees WITHOUT issues that were selected alongside are carried in
``ok_employee_ids`` and always generated on confirm. Line creation is
delegated to ``hr.appraisal.batch._generate_appraisals_for_employees`` so
the evaluator rules (source batch / direct manager) apply identically.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrAppraisalBatchReview(models.TransientModel):
    _name = 'hr.appraisal.batch.review'
    _description = 'Employees Needing Review Before Appraisal'

    batch_id = fields.Many2one(
        'hr.appraisal.batch', string='Batch', required=True, ondelete='cascade',
    )
    date_from = fields.Date(related='batch_id.date_from', readonly=True)
    date_to = fields.Date(related='batch_id.date_to', readonly=True)
    ok_employee_ids = fields.Many2many(
        'hr.employee',
        'hr_appraisal_review_ok_rel', 'wizard_id', 'employee_id',
        string='Employees Without Issues',
        context={'active_test': False},
        help='Selected employees with no issue in the period — always '
             'generated when confirming.',
    )
    line_ids = fields.One2many(
        'hr.appraisal.batch.review.line', 'wizard_id',
        string='Employees With Issues',
    )
    line_count = fields.Integer(compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)

    @api.model
    def _prepare_line_commands(self, batch, employees):
        """One2many create commands for every employee with an issue in the
        batch period. Employees without issues are silently left out."""
        issues = batch._employee_period_issues(employees)
        commands = []
        for employee in employees:
            issue = issues.get(employee.id)
            if not issue:
                continue
            if issue['no_contract']:
                contract_issue = 'no_contract'
            elif issue['contract_boundary']:
                contract_issue = 'boundary'
            else:
                contract_issue = 'none'
            commands.append((0, 0, {
                'employee_id': employee.id,
                'issue_job_change': len(issue['jobs']) > 1,
                'issue_contract': contract_issue,
                'issue_summary': issue['summary'],
                'period_job_ids': [(6, 0, issue['jobs'].ids)],
                # Leave the job empty on a job change: HR must choose.
                'job_id': False if len(issue['jobs']) > 1 else employee.job_id.id,
            }))
        return commands

    def action_confirm(self):
        self.ensure_one()
        batch = self.batch_id
        batch._assert_can_generate_appraisals()
        included = self.line_ids.filtered(lambda l: l.decision == 'include')
        missing_job = included.filtered(
            lambda l: l.issue_job_change and not l.job_id)
        if missing_job:
            raise UserError(_(
                "Choose the job position to appraise for:\n%s"
            ) % "\n".join(missing_job.mapped('employee_id.name')))

        employees = self.ok_employee_ids | included.mapped('employee_id')
        # Re-filter duplicates defensively (another user may have generated
        # appraisals between the two wizard steps).
        employees -= batch.appraisal_ids.mapped('employee_id')
        if not employees:
            raise UserError(_(
                "No employees left to generate — everyone was either "
                "excluded or already has an appraisal in this batch."
            ))
        job_by_employee = {
            line.employee_id.id: line.job_id.id
            for line in included if line.issue_job_change and line.job_id
        }
        batch._generate_appraisals_for_employees(employees, job_by_employee)

        # Plain text — message_post escapes HTML in interpolated bodies.
        if job_by_employee:
            batch.message_post(body=_(
                "Job position chosen for %(count)s employee(s) who changed "
                "job in the period %(date_from)s → %(date_to)s: %(names)s"
            ) % {
                'count': len(job_by_employee),
                'date_from': batch.date_from,
                'date_to': batch.date_to,
                'names': "، ".join(
                    "%s (%s)" % (l.employee_id.name, l.job_id.name)
                    for l in included if l.issue_job_change),
            })
        excluded = self.line_ids.filtered(lambda l: l.decision == 'exclude')
        if excluded:
            batch.message_post(body=_(
                "Skipped %(count)s employee(s) after review of the period "
                "%(date_from)s → %(date_to)s: %(names)s"
            ) % {
                'count': len(excluded),
                'date_from': batch.date_from,
                'date_to': batch.date_to,
                'names': "، ".join(
                    "%s (%s)" % (l.employee_id.name, l.issue_summary)
                    for l in excluded),
            })
        return {'type': 'ir.actions.act_window_close'}


class HrAppraisalBatchReviewLine(models.TransientModel):
    _name = 'hr.appraisal.batch.review.line'
    _description = 'Employee Needing Review Before Appraisal'
    _order = 'id'

    wizard_id = fields.Many2one(
        'hr.appraisal.batch.review', required=True, ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, readonly=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Department', readonly=True,
    )
    issue_job_change = fields.Boolean(string='Changed Job', readonly=True)
    issue_contract = fields.Selection([
        ('none', ''),
        ('boundary', 'Contract starts/ends in period'),
        ('no_contract', 'No active contract'),
    ], string='Contract', default='none', readonly=True)
    issue_summary = fields.Char(string='Issue', readonly=True)
    period_job_ids = fields.Many2many(
        'hr.job', 'hr_appraisal_review_line_job_rel', 'line_id', 'job_id',
        string='Positions Held In Period', readonly=True,
    )
    job_id = fields.Many2one(
        'hr.job', string='Appraise As',
        domain="[('id', 'in', period_job_ids)]",
        help="Job position this appraisal will be for. Required for "
             "employees who changed job during the period.",
    )
    decision = fields.Selection([
        ('include', 'Add to Batch'),
        ('exclude', "Don't Add"),
    ], string='Decision', default='include', required=True)
