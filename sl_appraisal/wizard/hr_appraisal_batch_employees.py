from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrAppraisalBatchEmployees(models.TransientModel):
    _name = 'hr.appraisal.batch.employees'
    _description = 'Generate Appraisals for Selected Employees'

    batch_id = fields.Many2one(
        'hr.appraisal.batch',
        string='Batch',
        default=lambda self: self.env.context.get('active_id'),
        readonly=True,
    )
    company_id = fields.Many2one('res.company', string='Company')
    department_id = fields.Many2one('hr.department', string='Department')
    job_id = fields.Many2one('hr.job', string='Job Position')
    work_location_id = fields.Many2one('hr.work.location', string='Work Location')
    manager_id = fields.Many2one('hr.employee', string='General Manager')
    employee_search = fields.Char(string='Search')
    employee_ids = fields.Many2many(
        'hr.employee',
        'hr_appraisal_batch_employee_rel',
        'wizard_id',
        'employee_id',
        string='Employees',
        # Without active_test=False, archived (departed) employees silently
        # vanish when the M2M is read back — they must stay selectable so
        # the review wizard can decide about them explicitly.
        context={'active_test': False},
        domain="[('appraisal_eligible', '=', True), ('id', 'not in', issue_employee_ids)]",
    )
    # Employees with a job change / contract issue in the batch period. They
    # are hidden from the picker above and handled one by one in the review
    # wizard (button "Review employees with issues").
    issue_employee_ids = fields.Many2many(
        'hr.employee',
        'hr_appraisal_batch_employee_issue_rel',
        'wizard_id',
        'employee_id',
        string='Employees With Issues',
        compute='_compute_issue_employees',
        context={'active_test': False},
    )
    issue_count = fields.Integer(compute='_compute_issue_employees')

    @api.depends('batch_id')
    def _compute_issue_employees(self):
        for wizard in self:
            batch = wizard.batch_id
            if not batch:
                wizard.issue_employee_ids = [(5, 0, 0)]
                wizard.issue_count = 0
                continue
            scope = batch._review_scope_employees()
            issues = batch._employee_period_issues(scope)
            wizard.issue_employee_ids = [(6, 0, list(issues))]
            wizard.issue_count = len(issues)

    @api.onchange('company_id', 'department_id', 'job_id', 'work_location_id', 'manager_id', 'employee_search')
    def _onchange_employee_filters(self):
        return {'domain': {'employee_ids': self._get_employee_domain()}}

    def _get_employee_domain(self):
        self.ensure_one()
        # Employee card → Appraisal & Bonus tab → "Appraisal" unchecked
        # means the employee cannot take appraisals at all. Employees with
        # period issues go through the review wizard instead.
        domain = [
            ('appraisal_eligible', '=', True),
            ('id', 'not in', self.issue_employee_ids.ids),
        ]
        if self.company_id:
            domain.append(('company_id', '=', self.company_id.id))
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.job_id:
            domain.append(('job_id', '=', self.job_id.id))
        if self.work_location_id:
            domain.append(('work_location_id', '=', self.work_location_id.id))
        if self.manager_id:
            domain.append(('parent_id', '=', self.manager_id.id))
        if self.employee_search:
            domain.extend([
                '|', '|', '|',
                ('name', 'ilike', self.employee_search),
                ('work_email', 'ilike', self.employee_search),
                ('identification_id', 'ilike', self.employee_search),
                ('job_id.name', 'ilike', self.employee_search),
            ])
        return domain

    def action_select_all_filtered(self):
        self.ensure_one()
        employees = self.env['hr.employee'].search(self._get_employee_domain())
        self.employee_ids = [(6, 0, employees.ids)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_open_review_wizard(self):
        """Review every employee with a period issue (hidden from the picker)."""
        self.ensure_one()
        batch = self.batch_id
        if not batch:
            raise UserError(_("No appraisal batch was found."))
        batch._assert_can_generate_appraisals()
        flagged = self.issue_employee_ids - batch.appraisal_ids.mapped('employee_id')
        if not flagged:
            raise UserError(_("No employee currently needs review for this period."))
        return batch._open_review_wizard(flagged)

    def action_generate_appraisals(self):
        self.ensure_one()
        batch = self.batch_id
        if not batch:
            raise UserError(_("No appraisal batch was found."))
        batch._assert_can_generate_appraisals()
        if not self.employee_ids:
            raise UserError(_("You must select at least one employee."))

        existing_employees = batch.appraisal_ids.mapped('employee_id')
        duplicates = self.employee_ids & existing_employees
        if duplicates:
            raise UserError(_(
                "These employees already exist in this batch:\n%s"
            ) % "\n".join(duplicates.mapped('name')))

        # Defensive re-check on the actual selection: anyone with a job
        # change / contract issue in the period is decided in the review
        # wizard, never generated silently.
        issues = batch._employee_period_issues(self.employee_ids)
        flagged = self.employee_ids.filtered(lambda e: e.id in issues)
        if flagged:
            return batch._open_review_wizard(flagged, self.employee_ids - flagged)

        batch._generate_appraisals_for_employees(self.employee_ids)
        return {'type': 'ir.actions.act_window_close'}
