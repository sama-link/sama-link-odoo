"""Wizard: general bonus policy settings (HR Manager / Admin).

Thin UI over ``ir.config_parameter`` so HR can tune bonus policy without
developer mode. Currently exposes the minimum evaluation % — employees
scoring below it receive ZERO bonus (see ``sl.bonus.calculator``).
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

PARAM_MIN_EVAL = 'sl_monthly_bonus.min_evaluation_percent'


class SlBonusSettings(models.TransientModel):
    _name = 'sl.bonus.settings'
    _description = 'Bonus Policy Settings'

    min_evaluation_percent = fields.Float(
        string='Minimum Evaluation %',
        digits=(16, 2),
        help='Employees whose appraisal evaluation is below this percentage '
             'receive ZERO bonus (the line is excluded with a clear Arabic '
             'reason). Set to 0 to disable the rule entirely.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res['min_evaluation_percent'] = self.env[
            'sl.bonus.calculator'
        ]._get_min_evaluation_percent()
        return res

    def _ensure_access(self):
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only HR Manager / Admin can change bonus settings."))

    @api.constrains('min_evaluation_percent')
    def _check_min_evaluation_percent(self):
        for rec in self:
            if not 0 <= rec.min_evaluation_percent <= 100:
                raise ValidationError(_(
                    "Minimum Evaluation % must be between 0 and 100."
                ))

    def action_save(self):
        self.ensure_one()
        self._ensure_access()
        self.env['ir.config_parameter'].sudo().set_param(
            PARAM_MIN_EVAL, str(self.min_evaluation_percent),
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Bonus Settings'),
                'message': _(
                    "Saved — employees below %s%% evaluation now receive zero bonus. "
                    "Recompute open batches for the change to take effect."
                ) % f"{self.min_evaluation_percent:g}",
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
