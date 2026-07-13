from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusSalesTier(models.Model):
    """Sales commission tiers — global defaults plus per-employee overrides.

    Each tier maps a minimum target-achievement % to a commission percentage
    of the employee's ACHIEVED (collected) sales. The calculator picks the
    highest tier whose ``achievement_min`` is reached.

    Records with ``target_id`` set belong to that employee's sales target and
    override the defaults; records without it are the GLOBAL default table
    used for every employee that has no tiers of their own. Both are managed
    from Bonus → Configuration → Sales Targets & Commissions.
    """
    _name = 'sl.bonus.sales.tier'
    _description = 'Sales Commission Tier'
    _order = 'achievement_min'

    target_id = fields.Many2one(
        'sl.bonus.target', string='Sales Target',
        ondelete='cascade', index=True,
        help='When set, this tier applies only to the employee of this sales '
             'target. When empty, the tier is part of the global default table.',
    )
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
        """Return the highest GLOBAL tier whose achievement_min is reached
        (per-employee tiers are resolved via sl.bonus.target)."""
        winning = False
        for tier in self.sudo().search(
            [('target_id', '=', False)], order='achievement_min',
        ):
            if achievement_percent >= tier.achievement_min:
                winning = tier
        return winning
