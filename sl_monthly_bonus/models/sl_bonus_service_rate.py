from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusServiceRate(models.Model):
    _name = 'sl.bonus.service.rate'
    _description = 'Service Bonus Percentage by Job Position'
    _order = 'job_id, date_from desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        required=True, ondelete='restrict',
    )
    percentage = fields.Float(
        string='Percentage %',
        required=True,
        help='Percentage of basic salary (e.g. enter 20 for 20%). Suggested range 15–35%.',
    )
    date_from = fields.Date(
        string='Effective From', required=True, default=fields.Date.context_today,
    )
    date_to = fields.Date(string='Effective To')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Note')

    @api.depends('job_id', 'percentage')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.job_id.name or ''} — {rec.percentage:.2f}%" if rec.job_id else rec.percentage and f"{rec.percentage:.2f}%" or '/'

    @api.constrains('percentage')
    def _check_percentage(self):
        for rec in self:
            if rec.percentage < 0 or rec.percentage > 100:
                raise ValidationError(_("Service percentage must be between 0 and 100."))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to and rec.date_from and rec.date_to < rec.date_from:
                raise ValidationError(_("Effective To must be after Effective From."))

    @api.model
    def get_rate_for(self, job_id, on_date):
        if not job_id or not on_date:
            return 0.0
        rec = self.search([
            ('job_id', '=', job_id),
            ('date_from', '<=', on_date),
            '|', ('date_to', '=', False), ('date_to', '>=', on_date),
        ], order='date_from desc', limit=1)
        return rec.percentage if rec else 0.0
