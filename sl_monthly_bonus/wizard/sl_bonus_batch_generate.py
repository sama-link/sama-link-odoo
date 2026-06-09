"""Select-employees wizard for a bonus batch (payslip-"Generate" style).

Opens with all active employees pre-selected, a search box to narrow the list,
then sets the batch's employees and moves it to Data Ready (it does NOT compute —
the user clicks "Compute Bonuses" next, so the Data Ready stage is preserved).
Calculator logic is untouched — this only decides WHICH employees are in scope.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SlBonusBatchGenerateWizard(models.TransientModel):
    _name = 'sl.bonus.batch.generate.wizard'
    _description = 'Select Employees for Bonus Batch'

    batch_id = fields.Many2one('sl.bonus.batch', string='Batch', required=True)
    employee_filter = fields.Char(string='Search')
    employee_ids = fields.Many2many('hr.employee', string='Employees')

    def _ctx_batch(self):
        ctx = self.env.context
        bid = ctx.get('default_batch_id') or (
            ctx.get('active_id') if ctx.get('active_model') == 'sl.bonus.batch' else False)
        return self.env['sl.bonus.batch'].browse(bid) if bid else self.env['sl.bonus.batch']

    def _employee_domain(self, batch, text=None):
        company_ids = [batch.company_id.id, False] if batch else [self.env.company.id, False]
        domain = [('active', '=', True), ('company_id', 'in', company_ids)]
        text = (text or '').strip()
        if text:
            Emp = self.env['hr.employee']
            terms = [('name', 'ilike', text)]
            for fname in ('barcode', 'identification_id', 'registration_number'):
                if fname in Emp._fields:
                    terms.append((fname, 'ilike', text))
            domain += ['|'] * (len(terms) - 1) + terms
        return domain

    def _find_employees(self, batch, text=None):
        return self.env['hr.employee'].sudo().search(self._employee_domain(batch, text))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        batch = self._ctx_batch()
        if batch:
            res.setdefault('batch_id', batch.id)
            if 'employee_ids' in fields_list:
                res['employee_ids'] = [(6, 0, self._find_employees(batch).ids)]
        return res

    def action_search(self):
        """Filter the employee list by the search text (name / code).
        Empty search reloads all active employees."""
        self.ensure_one()
        emps = self._find_employees(self.batch_id, self.employee_filter)
        self.employee_ids = [(6, 0, emps.ids)]
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate(self):
        """Set the batch's employees and move it to Data Ready (no compute).

        The Data Ready stage is intentionally preserved — the user then clicks
        "Compute Bonuses" on the batch to generate the lines."""
        self.ensure_one()
        if not self.employee_ids:
            raise UserError(_("Select at least one employee."))
        batch = self.batch_id
        if batch.state in ('approved', 'locked'):
            raise UserError(_("This batch is %s and can no longer be changed.") % batch.state)
        batch.employee_ids = [(6, 0, self.employee_ids.ids)]
        if batch.state == 'draft':
            batch.action_mark_data_ready()
        return batch._return_form_action()
