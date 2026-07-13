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
        # the contract-warning wizard can decide about them explicitly.
        context={'active_test': False},
    )

    @api.onchange('company_id', 'department_id', 'job_id', 'work_location_id', 'manager_id', 'employee_search')
    def _onchange_employee_filters(self):
        return {'domain': {'employee_ids': self._get_employee_domain()}}

    def _get_employee_domain(self):
        self.ensure_one()
        domain = []
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

    def action_generate_appraisals(self):
        self.ensure_one()
        batch = self.batch_id
        if not batch:
            raise UserError(_("No appraisal batch was found."))
        if batch.state != 'draft':
            raise UserError(_("Employees can only be added while the batch is in Draft state."))
        if not self.employee_ids:
            raise UserError(_("You must select at least one employee."))

        existing_employees = batch.appraisal_ids.mapped('employee_id')
        duplicates = self.employee_ids & existing_employees
        if duplicates:
            raise UserError(_(
                "These employees already exist in this batch:\n%s"
            ) % "\n".join(duplicates.mapped('name')))

        # Employees with no contract overlapping the batch period are not
        # generated silently — HR decides per employee in a warning wizard.
        no_contract = self.employee_ids.filtered(
            lambda e: not e._has_active_contract_in_period(
                batch.date_from, batch.date_to)
        )
        if no_contract:
            warning_wizard = self.env['hr.appraisal.batch.contract.warning'].create({
                'batch_id': batch.id,
                'ok_employee_ids': [(6, 0, (self.employee_ids - no_contract).ids)],
                'line_ids': [
                    (0, 0, {'employee_id': emp.id}) for emp in no_contract
                ],
            })
            return {
                'name': _('Employees Without Active Contract'),
                'type': 'ir.actions.act_window',
                'res_model': 'hr.appraisal.batch.contract.warning',
                'res_id': warning_wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        batch._generate_appraisals_for_employees(self.employee_ids)
        return {'type': 'ir.actions.act_window_close'}
