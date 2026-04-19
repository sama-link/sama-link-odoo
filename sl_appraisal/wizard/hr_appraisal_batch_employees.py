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

        appraisal_model = self.env['hr.appraisal']
        for employee in self.employee_ids:
            vals = {
                'employee_id': employee.id,
                'company_id': employee.company_id.id or batch.company_id.id,
                'appraisal_deadline': batch.date_deadline,
                'date_from': batch.date_from,
                'date_to': batch.date_to,
                'appraisal_batch_id': batch.id,
            }
            if employee.parent_id.user_id:
                vals['hr_manager_ids'] = [(6, 0, employee.parent_id.ids)]
            appraisal = appraisal_model.create(vals)
            if employee.employee_skill_ids and not appraisal.skills_populated:
                appraisal.action_populate_skills()

        batch.message_post(
            body=_("Generated %s appraisal(s) from the batch wizard.") % len(self.employee_ids)
        )
        return {'type': 'ir.actions.act_window_close'}
