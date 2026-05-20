from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SlBonusComputeWizard(models.TransientModel):
    """HR-friendly wizard to compute / recompute bonuses for a single employee
    or a hand-picked subset, without touching the rest of the batch.

    Useful after correcting an appraisal or staging data for one person:
    only their line is refreshed, the rest stays as-is, and manual overrides
    on the chosen line are preserved.
    """
    _name = 'sl.bonus.compute.wizard'
    _description = 'Compute Bonuses for Selected Employees'

    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Bonus Batch', required=True, ondelete='cascade',
    )
    scope = fields.Selection([
        ('selected', 'Selected employees only'),
        ('all', 'All active employees (full recompute)'),
    ], default='selected', required=True, string='Scope')
    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        help='Pick one or more employees to (re)compute.',
    )
    affected_count_preview = fields.Integer(
        compute='_compute_preview', string='Will Touch (preview)',
    )

    @api.depends('scope', 'employee_ids')
    def _compute_preview(self):
        for rec in self:
            if rec.scope == 'all':
                rec.affected_count_preview = self.env['hr.employee'].search_count([
                    ('active', '=', True),
                ])
            else:
                rec.affected_count_preview = len(rec.employee_ids)

    def action_run(self):
        self.ensure_one()
        if self.scope == 'all':
            self.batch_id.action_compute()
            n = len(self.batch_id.line_ids)
            return self._notify(_("Recomputed all employees (%s lines).") % n)
        if not self.employee_ids:
            raise UserError(_("Please pick at least one employee, or switch the scope to 'All active employees'."))
        affected = self.batch_id.action_compute_employees(self.employee_ids.ids)
        return self._notify(_("Recomputed %s line(s).") % len(affected))

    def _notify(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Compute Done'),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'sl.bonus.batch',
                    'res_id': self.batch_id.id,
                    'view_mode': 'form',
                    'target': 'current',
                },
            },
        }
