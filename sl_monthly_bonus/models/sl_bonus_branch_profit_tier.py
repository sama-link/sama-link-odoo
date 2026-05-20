from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusBranchProfitTier(models.Model):
    """Branch profitability tiers configuration.

    Three tiers per requirements:
      - factor < 1 → lowest percentage (tier=low)
      - 1 ≤ factor ≤ 1.5 → base percentage (tier=base)
      - factor > 1.5 → highest percentage (tier=high)

    Three tier records are created on install and can be edited by HR.
    """
    _name = 'sl.bonus.branch.profit.tier'
    _description = 'Branch Profitability Tier (Bonus)'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True)
    code = fields.Selection(
        [('low', 'Low (< 1)'), ('base', 'Base (1 – 1.5)'), ('high', 'High (> 1.5)')],
        string='Tier Code', required=True,
    )
    sequence = fields.Integer(default=10)
    factor_min = fields.Float(string='Factor Min (inclusive)')
    factor_max = fields.Float(string='Factor Max (inclusive)')
    factor_min_inclusive = fields.Boolean(string='Min Inclusive', default=True)
    factor_max_inclusive = fields.Boolean(string='Max Inclusive', default=True)
    description = fields.Text(string='Description')

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Each tier code (low/base/high) must be unique.'),
    ]

    @api.model
    def get_tier_for_factor(self, factor):
        """Return the tier matching a numeric profitability factor."""
        if factor is None:
            return self.browse()
        tiers = self.search([])
        for tier in tiers:
            ok_min = True
            ok_max = True
            if tier.factor_min:
                ok_min = factor >= tier.factor_min if tier.factor_min_inclusive else factor > tier.factor_min
            if tier.factor_max:
                ok_max = factor <= tier.factor_max if tier.factor_max_inclusive else factor < tier.factor_max
            # Use code-based rules to be deterministic regardless of overlapping bounds.
            if tier.code == 'low' and factor < 1:
                return tier
            if tier.code == 'base' and 1 <= factor <= 1.5:
                return tier
            if tier.code == 'high' and factor > 1.5:
                return tier
        return self.browse()
