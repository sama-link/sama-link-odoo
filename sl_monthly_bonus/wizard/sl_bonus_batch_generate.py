"""Select-employees / generate wizard for a bonus batch.

Mirrors the payslip-batch "Generate" UX: opens with all active employees
pre-selected (optionally narrowed by department), then generates the batch
lines for exactly the chosen employees. Calculator logic is untouched — this
only decides WHICH employees the existing engine computes.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SlBonusBatchGenerateWizard(models.TransientModel):
    _name = 'sl.bonus.batch.generate.wizard'
    _description = 'Generate Bonus Lines — Select Employees'

    batch_id = fields.Many2one('sl.bonus.batch', string='Batch', required=True)
    department_ids = fields.Many2many('hr.department', string='Filter by Departments')
    employee_ids = fields.Many2many('hr.employee', string='Employees')

    def _ctx_batch(self):
        ctx = self.env.context
        bid = ctx.get('default_batch_id') or (
            ctx.get('active_id') if ctx.get('active_model') == 'sl.bonus.batch' else False)
        return self.env['sl.bonus.batch'].browse(bid) if bid else self.env['sl.bonus.batch']

    def _batch_employees(self, batch, departments=None):
        domain = [
            ('active', '=', True),
            ('company_id', 'in', [batch.company_id.id, False] if batch else [self.env.company.id, False]),
        ]
        if departments:
            domain.append(('department_id', 'child_of', departments.ids))
        return self.env['hr.employee'].sudo().search(domain)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        batch = self._ctx_batch()
        if batch:
            res.setdefault('batch_id', batch.id)
            if 'employee_ids' in fields_list:
                res['employee_ids'] = [(6, 0, self._batch_employees(batch).ids)]
        return res

    def action_apply_filter(self):
        """Replace the employee list with everyone in the selected departments
        (or all active employees when no department is chosen)."""
        self.ensure_one()
        emps = self._batch_employees(self.batch_id, self.department_ids or None)
        self.employee_ids = [(6, 0, emps.ids)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate(self):
        """Set the batch's employees and generate (compute) their lines."""
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_("Select at least one employee."))
        batch = self.batch_id
        if batch.state in ('approved', 'locked'):
            raise UserError(_("This batch is %s and can no longer be regenerated.") % batch.state)
        batch.employee_ids = [(6, 0, self.employee_ids.ids)]
        if batch.state == 'draft':
            batch.action_mark_data_ready()
        batch.action_compute()
        return batch._return_form_action()
