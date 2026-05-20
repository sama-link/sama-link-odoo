from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusManualAdjustWizard(models.TransientModel):
    _name = 'sl.bonus.manual.adjust.wizard'
    _description = 'Manual Bonus Adjustment'

    line_id = fields.Many2one(
        'sl.bonus.batch.line', string='Line', required=True,
    )
    employee_id = fields.Many2one(
        related='line_id.employee_id', readonly=True,
    )
    current_amount = fields.Monetary(
        string='Current Amount', readonly=True,
        related='line_id.bonus_amount', currency_field='currency_id',
    )
    new_amount = fields.Monetary(
        string='New Amount', required=True,
        currency_field='currency_id',
    )
    reason = fields.Text(string='Reason', required=True)
    currency_id = fields.Many2one(
        related='line_id.currency_id', readonly=True,
    )

    @api.constrains('new_amount')
    def _check_amount(self):
        for rec in self:
            if rec.new_amount < 0:
                raise ValidationError(_("New amount must be non-negative."))

    def action_apply(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise ValidationError(_("A reason is mandatory for any manual override."))
        self.line_id.action_apply_manual_override(self.new_amount, self.reason)
        return {'type': 'ir.actions.act_window_close'}
