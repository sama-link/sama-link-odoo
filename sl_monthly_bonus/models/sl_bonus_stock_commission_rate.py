from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusStockCommissionRate(models.Model):
    _name = 'sl.bonus.stock.commission.rate'
    _description = 'Stock Purchasing Commission Percentage'
    _order = 'date_from desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    percentage = fields.Float(
        string='Commission %', required=True,
        help='Commission percentage of stock sales value (e.g. 1.5 for 1.5%).',
    )
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        help='Optional. If set, this rate applies only to this job position. '
             'Otherwise it is the default rate for all stock-purchase employees.',
    )
    date_from = fields.Date(string='Effective From', required=True,
                            default=fields.Date.context_today)
    date_to = fields.Date(string='Effective To')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    @api.depends('job_id', 'percentage')
    def _compute_name(self):
        for rec in self:
            label = rec.job_id.name or _('All stock positions')
            rec.name = f"{label} — {rec.percentage:.3f}%"

    @api.constrains('percentage')
    def _check_percentage(self):
        for rec in self:
            if rec.percentage < 0 or rec.percentage > 100:
                raise ValidationError(_("Commission % must be between 0 and 100."))

    @api.model
    def get_rate_for(self, job_id, on_date):
        if not on_date:
            return 0.0
        # Prefer job-specific rate; fall back to default rate (no job).
        rec = self.search([
            ('job_id', '=', job_id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc', limit=1)
        if rec:
            return rec.percentage
        rec = self.search([
            ('job_id', '=', False),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc', limit=1)
        return rec.percentage if rec else 0.0
