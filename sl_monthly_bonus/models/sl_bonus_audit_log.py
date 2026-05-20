from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError


class SlBonusAuditLog(models.Model):
    """Immutable-by-default audit trail for bonus operations."""
    _name = 'sl.bonus.audit.log'
    _description = 'Bonus Audit Log'
    _order = 'create_date desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    user_id = fields.Many2one(
        'res.users', required=True, readonly=True,
        default=lambda self: self.env.user,
    )
    action = fields.Char(string='Action', required=True, readonly=True)
    model = fields.Char(string='Model', required=True, readonly=True)
    res_id = fields.Integer(string='Record ID', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    batch_id = fields.Many2one('sl.bonus.batch', string='Batch', readonly=True)
    old_value = fields.Text(string='Old Value', readonly=True)
    new_value = fields.Text(string='New Value', readonly=True)
    reason = fields.Text(string='Reason', readonly=True)
    company_id = fields.Many2one(
        'res.company', readonly=True,
        default=lambda self: self.env.company,
    )

    @api.depends('action', 'model', 'res_id', 'user_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.action or ''} on {rec.model or ''}#{rec.res_id or ''} by {rec.user_id.name or ''}"

    @api.model
    def log_change(self, model, res_id, action, old_value='', new_value='',
                   reason='', employee_id=False, batch_id=False):
        return self.sudo().create({
            'model': model,
            'res_id': res_id,
            'action': action,
            'old_value': old_value,
            'new_value': new_value,
            'reason': reason,
            'employee_id': employee_id or False,
            'batch_id': batch_id or False,
        })

    def write(self, vals):
        is_admin = self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
            or self.env.user.has_group('base.group_system')
        if not is_admin:
            raise AccessError(_("Audit log records are read-only."))
        return super().write(vals)

    def unlink(self):
        # Audit log must not be deletable, even by admin (per requirements).
        raise UserError(_("Audit log entries cannot be deleted."))
