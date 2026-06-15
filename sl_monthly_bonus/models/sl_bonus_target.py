from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusTarget(models.Model):
    """Monthly sales target per employee, with threshold-tier commission table."""
    _name = 'sl.bonus.target'
    _description = 'Sales Target (Monthly)'
    _order = 'period_start desc, employee_id'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, ondelete='cascade',
    )
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        related='employee_id.job_id', store=True, readonly=True,
    )
    period_start = fields.Date(
        string='Period',
        help='Legacy/optional. Targets are now valid for all time — one target '
             'per employee — so this date is no longer required.',
    )
    target_amount = fields.Monetary(
        string='Target', required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', store=True, readonly=True,
    )
    tier_ids = fields.One2many(
        'sl.bonus.target.tier', 'target_id', string='Threshold Tiers (legacy)',
        copy=True,
        help='Deprecated: commission tiers are now GLOBAL — see '
             'Bonus → Configuration → Sales Commission Tiers.',
    )
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    # One target per employee, valid for all time (no per-month uniqueness).
    # Enforced in Python so pre-existing duplicate rows don't break the upgrade.
    @api.constrains('employee_id', 'active')
    def _check_one_per_employee(self):
        for rec in self:
            if rec.active and rec.employee_id and self.search_count([
                ('employee_id', '=', rec.employee_id.id),
                ('active', '=', True),
                ('id', '!=', rec.id),
            ]):
                raise ValidationError(_(
                    "A sales target already exists for %s. Only one target per "
                    "employee is allowed (it is valid for all time)."
                ) % rec.employee_id.name)

    @api.depends('employee_id', 'target_amount')
    def _compute_name(self):
        for rec in self:
            label = rec.employee_id.name or _('Target')
            rec.name = f"{label} — {rec.target_amount or 0.0:.2f}"

    @api.constrains('target_amount')
    def _check_amount(self):
        for rec in self:
            if rec.target_amount < 0:
                raise ValidationError(_("Target amount must be non-negative."))

    @api.model
    def find_for(self, employee_id, period_date=None):
        """Return the employee's sales target (valid for all time).

        ``period_date`` is accepted for backward compatibility but ignored —
        there is one target per employee now.
        """
        if not employee_id:
            return self.browse()
        return self.search([
            ('employee_id', '=', employee_id),
            ('active', '=', True),
        ], order='id desc', limit=1)

    def get_tier_for_achievement(self, achievement_percent):
        """Return the highest tier whose achievement_min is satisfied (threshold).

        Returns False if no tier qualifies.
        """
        self.ensure_one()
        tiers = self.tier_ids.sorted(lambda t: t.achievement_min)
        winning = False
        for tier in tiers:
            if achievement_percent >= tier.achievement_min:
                winning = tier
        return winning


class SlBonusTargetTier(models.Model):
    _name = 'sl.bonus.target.tier'
    _description = 'Sales Target Threshold Tier'
    _order = 'achievement_min'

    target_id = fields.Many2one(
        'sl.bonus.target', string='Target', required=True, ondelete='cascade',
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Tier Name')
    achievement_min = fields.Float(
        string='Min Achievement %',
        required=True,
        help='Minimum target-achievement percentage to qualify for this tier (e.g. 80, 100, 110).',
    )
    commission_amount = fields.Monetary(
        string='Tier Commission',
        required=True, currency_field='currency_id',
        help='Total commission paid when this tier is reached (threshold system).',
    )
    currency_id = fields.Many2one(
        'res.currency', related='target_id.currency_id', store=True, readonly=True,
    )

    @api.constrains('achievement_min', 'commission_amount')
    def _check_values(self):
        for rec in self:
            if rec.achievement_min < 0:
                raise ValidationError(_("Min achievement must be non-negative."))
            if rec.commission_amount < 0:
                raise ValidationError(_("Tier commission must be non-negative."))
