from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusInstallationRate(models.Model):
    _name = 'sl.bonus.installation.rate'
    _description = 'Installation Fixed Monthly Bonus by Job Position'
    _order = 'job_id, date_from desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    job_id = fields.Many2one('hr.job', string='Job Position',
                             required=True, ondelete='restrict')
    fixed_amount = fields.Monetary(
        string='Fixed Monthly Bonus',
        required=True, currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    date_from = fields.Date(string='Effective From', required=True,
                            default=fields.Date.context_today)
    date_to = fields.Date(string='Effective To')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    @api.depends('job_id', 'fixed_amount')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.job_id.name or ''} — {rec.fixed_amount:.2f}" if rec.job_id else '/'

    @api.constrains('fixed_amount')
    def _check_amount(self):
        for rec in self:
            if rec.fixed_amount < 0:
                raise ValidationError(_("Fixed amount must be non-negative."))

    @api.model
    def get_amount_for(self, job_id, on_date):
        if not job_id or not on_date:
            return 0.0
        rec = self.search([
            ('job_id', '=', job_id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc', limit=1)
        return rec.fixed_amount if rec else 0.0
