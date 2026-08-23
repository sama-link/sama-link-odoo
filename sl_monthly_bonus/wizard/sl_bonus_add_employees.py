"""Wizard: Add Employees to a Bonus Batch.

Replaces the previous direct ``action_add_all_employees`` button — HR now
picks the employee set explicitly. Three modes:

  - ``specific``      pick individual employees via a M2M tag widget
  - ``all``           every active employee in the batch's company
  - ``by_department`` every active employee in one or more departments

The actual line creation is delegated to
``sl.bonus.batch._add_employees_to_lines`` so that duplicates against
existing ``line_ids`` and per-line @api.constrains uniqueness rules are
honored exactly the same way as the legacy entry point.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SlBonusAddEmployeesWizard(models.TransientModel):
    _name = 'sl.bonus.add.employees.wizard'
    _description = 'Add Employees to Bonus Batch'

    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Bonus Batch', required=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='batch_id.company_id', readonly=True,
    )
    mode = fields.Selection([
        ('specific', 'Specific employees'),
        ('all', 'All active employees'),
        ('by_department', 'By department(s)'),
    ], string='Selection', default='specific', required=True)
    employee_ids = fields.Many2many(
        'hr.employee', 'sl_bonus_add_emp_wiz_emp_rel',
        'wizard_id', 'employee_id',
        string='Employees',
        domain="[('company_id', 'in', [company_id, False]), ('bonus_eligible', '=', True)]",
        # active_test=False so archived (departed) employees survive the
        # M2M read-back — otherwise they are silently dropped on confirm.
        context={'active_test': False},
        help='Selected employees — used when mode is "Specific employees". '
             'Archived (departed) employees can be added too.',
    )
    department_ids = fields.Many2many(
        'hr.department', 'sl_bonus_add_emp_wiz_dep_rel',
        'wizard_id', 'department_id',
        string='Departments',
        help='Picked departments — used when mode is "By department(s)".',
    )
    preview_count = fields.Integer(
        string='Will Add', compute='_compute_preview_count',
        help='Number of NEW lines this wizard will create after duplicate filtering.',
    )

    @api.depends('mode', 'employee_ids', 'department_ids', 'batch_id', 'batch_id.line_ids')
    def _compute_preview_count(self):
        for wiz in self:
            if not wiz.batch_id:
                wiz.preview_count = 0
                continue
            candidate = wiz._candidate_employees()
            existing_ids = set(wiz.batch_id.line_ids.mapped('employee_id.id'))
            wiz.preview_count = sum(
                1 for e in candidate if e.id not in existing_ids
            )

    def _candidate_employees(self):
        """Resolve the candidate ``hr.employee`` recordset for the chosen mode."""
        self.ensure_one()
        # Employee card → Appraisal & Bonus tab → "Bonus" unchecked means
        # the employee cannot take a bonus: never a candidate, in any mode.
        if self.mode == 'all':
            return self.env['hr.employee'].sudo().search([
                ('company_id', 'in', [self.company_id.id, False]),
                ('active', '=', True),
                ('bonus_eligible', '=', True),
            ])
        if self.mode == 'by_department':
            if not self.department_ids:
                return self.env['hr.employee']
            return self.env['hr.employee'].sudo().search([
                ('department_id', 'in', self.department_ids.ids),
                ('company_id', 'in', [self.company_id.id, False]),
                ('active', '=', True),
                ('bonus_eligible', '=', True),
            ])
        # specific
        return self.employee_ids.filtered('bonus_eligible')

    def action_confirm(self):
        """Create the lines and close the wizard."""
        self.ensure_one()
        if not self.batch_id:
            raise UserError(_("No bonus batch selected."))
        candidates = self._candidate_employees()
        if not candidates:
            raise UserError(_(
                "No employees match the selection. Pick at least one "
                "employee or department, or choose 'All active employees'."
            ))
        created = self.batch_id._add_employees_to_lines(candidates)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employees added'),
                'message': _("Added %(new)s new bonus line(s); %(skipped)s already present.") % {
                    'new': len(created),
                    'skipped': len(candidates) - len(created),
                },
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
