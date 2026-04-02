from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    appraisal_ids = fields.One2many(
        'hr.appraisal', 'employee_id',
        string='Appraisals',
        help="All appraisals for this employee")

    appraisal_count = fields.Integer(
        string='Appraisal Count',
        compute='_compute_appraisal_count')

    last_appraisal_date = fields.Date(
        string='Last Appraisal',
        compute='_compute_last_appraisal_date',
        help="Date of the most recent finalized appraisal")

    @api.depends('appraisal_ids')
    def _compute_appraisal_count(self):
        appraisal_data = self.env['hr.appraisal'].sudo().read_group(
            domain=[('employee_id', 'in', self.ids)],
            fields=['employee_id'],
            groupby=['employee_id'],
        )
        mapped_data = {
            item['employee_id'][0]: item['employee_id_count']
            for item in appraisal_data
        }
        for employee in self:
            employee.appraisal_count = mapped_data.get(employee.id, 0)

    @api.depends('appraisal_ids', 'appraisal_ids.state')
    def _compute_last_appraisal_date(self):
        for employee in self:
            finalized = employee.appraisal_ids.filtered(
                lambda a: a.state == 'hr_finalization'
            ).sorted('appraisal_deadline', reverse=True)
            employee.last_appraisal_date = (
                finalized[0].appraisal_deadline if finalized else False)

    def action_open_appraisals(self):
        """Open appraisals list for this employee."""
        self.ensure_one()
        return {
            'name': f'Appraisals — {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.appraisal',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_open_my_employee(self):
        """Override to return current employee's My Info form."""
        employee = self.env.user.employee_id
        if not employee:
            raise models.UserError("No employee linked to your user.")
        return {
            'name': 'My Info',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'form',
            'res_id': employee.id,
            'view_id': self.env.ref(
                'samalink_security_groups.hr_employee_my_info_form_view').id,
            'target': 'current',
        }
