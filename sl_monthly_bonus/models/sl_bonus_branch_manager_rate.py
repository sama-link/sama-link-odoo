from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusBranchManagerRate(models.Model):
    """Percentages of basic salary granted to a branch/area manager per profitability tier.

    Each record holds the three percentages (low / base / high) for a job position
    (or company-wide default when job_id is unset).
    """
    _name = 'sl.bonus.branch.manager.rate'
    _description = 'Branch Manager Bonus Rate by Profitability Tier'
    _order = 'job_id, date_from desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        help='Leave blank for a company-wide default.',
    )
    pct_low = fields.Float(string='% when factor < 1', required=True)
    pct_base = fields.Float(string='% when 1 ≤ factor ≤ 1.5', required=True,
                            help='Base percentage (factor in [1, 1.5]).')
    pct_high = fields.Float(string='% when factor > 1.5', required=True)
    date_from = fields.Date(string='Effective From', required=True,
                            default=fields.Date.context_today)
    date_to = fields.Date(string='Effective To')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    @api.depends('job_id', 'pct_base')
    def _compute_name(self):
        for rec in self:
            label = rec.job_id.name or _('Default')
            rec.name = f"{label} — base {rec.pct_base:.2f}%"

    @api.constrains('pct_low', 'pct_base', 'pct_high')
    def _check_percentages(self):
        for rec in self:
            for v in (rec.pct_low, rec.pct_base, rec.pct_high):
                if v < 0 or v > 100:
                    raise ValidationError(_("All branch manager percentages must be between 0 and 100."))

    @api.model
    def get_percentage_for(self, job_id, factor, on_date):
        """Return the % for a branch manager based on job and branch profit factor."""
        if not on_date:
            return 0.0
        rec = self.search([
            ('job_id', '=', job_id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc', limit=1)
        if not rec:
            rec = self.search([
                ('job_id', '=', False),
                ('date_from', '<=', on_date),
                '|', ('date_to', '=', False), ('date_to', '>=', on_date),
            ], order='date_from desc', limit=1)
        if not rec:
            return 0.0
        if factor is None:
            return 0.0
        if factor < 1:
            return rec.pct_low
        if factor <= 1.5:
            return rec.pct_base
        return rec.pct_high
