from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusEdaraMapping(models.Model):
    """Map an Edara identifier (per role) to an Odoo employee.

    Roles correspond to where the Edara record is collected from:
      - sales: salesperson in Edara invoices
      - stock_purchasing: stock purchase responsible
      - installation: installation technician/supervisor
    """
    _name = 'sl.bonus.edara.mapping'
    _description = 'Edara → Odoo Employee Mapping'
    _order = 'employee_id, role'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, ondelete='cascade',
    )
    edara_external_id = fields.Char(
        string='Edara External ID', required=True,
        help='The identifier used by Edara for this person in the given role.',
    )
    role = fields.Selection([
        ('sales', 'Sales'),
        ('stock_purchasing', 'Stock Purchasing'),
        ('installation', 'Installation'),
    ], required=True, string='Role')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    _sql_constraints = [
        ('uniq_edara_role',
         'unique(edara_external_id, role)',
         'This Edara ID is already mapped for the given role.'),
    ]

    @api.depends('employee_id', 'role', 'edara_external_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.employee_id.name or '/'} — {rec.role or ''} — {rec.edara_external_id or ''}"

    @api.model
    def resolve_employee(self, edara_id, role):
        if not edara_id or not role:
            return self.env['hr.employee'].browse()
        rec = self.search([
            ('edara_external_id', '=', edara_id),
            ('role', '=', role),
        ], limit=1)
        return rec.employee_id
