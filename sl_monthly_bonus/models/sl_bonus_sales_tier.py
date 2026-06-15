from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusSalesTier(models.Model):
    """GLOBAL sales commission tiers — the same thresholds apply to ALL employees.

    Each tier maps a minimum target-achievement % to a commission percentage of
    the employee's own target amount. The calculator picks the highest tier whose
    ``achievement_min`` is reached, then commission = target_amount × percentage.
    """
    _name = 'sl.bonus.sales.tier'
    _description = 'Sales Commission Tier (global)'
    _order = 'achievement_min'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Tier Name')
    achievement_min = fields.Float(
        string='Min Achievement %', required=True,
        help='Minimum target-achievement percentage to qualify for this tier '
             '(e.g. 80, 100, 110). Achievement % = collected sales ÷ target × 100.',
    )
    commission_percent = fields.Float(
        string='Commission %', required=True,
        help='Commission paid at this tier, as a percentage of the ACHIEVED '
             '(collected) sales (e.g. 4 = 4% of collected sales). The tier is '
             'selected by achievement % = collected ÷ target × 100.',
    )

    @api.constrains('achievement_min', 'commission_percent')
    def _check_values(self):
        for rec in self:
            if rec.achievement_min < 0:
                raise ValidationError(_("Min achievement must be non-negative."))
            if rec.commission_percent < 0:
                raise ValidationError(_("Commission % must be non-negative."))

    @api.model
    def get_tier_for(self, achievement_percent):
        """Return the highest global tier whose achievement_min is reached."""
        winning = False
        for tier in self.sudo().search([], order='achievement_min'):
            if achievement_percent >= tier.achievement_min:
                winning = tier
        return winning
