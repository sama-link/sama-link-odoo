"""Smart link from an Appraisal Batch (sl_appraisal.hr.appraisal.batch) to its
matching Bonus Batch. Adds a "Compute Bonuses" smart button that finds or
creates a sl.bonus.batch for the same period and opens it in one click.
"""
from datetime import date
from calendar import monthrange
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrAppraisalBatch(models.Model):
    _inherit = 'hr.appraisal.batch'

    bonus_batch_id = fields.Many2one(
        'sl.bonus.batch', string='Linked Bonus Batch',
        compute='_compute_bonus_batch_id', store=False,
        help='Bonus batch that covers the same period and company as this '
             'appraisal batch. Created on demand from the Compute Bonuses button.',
    )
    bonus_batch_count = fields.Integer(compute='_compute_bonus_batch_id', store=False)
    bonus_batch_state = fields.Selection(
        related='bonus_batch_id.state', store=False, string='Bonus Batch State',
    )

    @api.depends('date_from', 'date_to', 'company_id')
    def _compute_bonus_batch_id(self):
        Batch = self.env['sl.bonus.batch'].sudo()
        for rec in self:
            period_start = rec.date_from and rec.date_from.replace(day=1) or False
            period_end = False
            if rec.date_to:
                y, m = rec.date_to.year, rec.date_to.month
                period_end = date(y, m, monthrange(y, m)[1])
            if not period_start or not period_end:
                rec.bonus_batch_id = False
                rec.bonus_batch_count = 0
                continue
            # Prefer the explicit appraisal_batch_id link if present.
            linked = Batch.search([('appraisal_batch_id', '=', rec.id)], limit=1)
            if linked:
                rec.bonus_batch_id = linked
                rec.bonus_batch_count = 1
                continue
            # Otherwise match by period.
            match = Batch.search([
                ('company_id', '=', rec.company_id.id),
                ('period_start', '=', period_start),
                ('period_end', '=', period_end),
            ], limit=1)
            rec.bonus_batch_id = match.id if match else False
            rec.bonus_batch_count = 1 if match else 0

    def action_open_or_create_bonus_batch(self):
        """Smart button — open the linked bonus batch, or create one if missing."""
        self.ensure_one()
        if not self.date_from or not self.date_to:
            raise UserError(_("Appraisal batch must have Period From / Period To set."))
        Batch = self.env['sl.bonus.batch']
        period_start = self.date_from.replace(day=1)
        y, m = self.date_to.year, self.date_to.month
        period_end = date(y, m, monthrange(y, m)[1])
        existing = Batch.search([
            '|',
            ('appraisal_batch_id', '=', self.id),
            '&',
            ('company_id', '=', self.company_id.id),
            '&',
            ('period_start', '=', period_start),
            ('period_end', '=', period_end),
        ], limit=1)
        if existing:
            if not existing.appraisal_batch_id:
                existing.sudo().appraisal_batch_id = self.id
            return existing._return_form_action()
        batch = Batch.create({
            'name': _('Bonus %s') % period_start.strftime('%Y-%m'),
            'period_start': period_start,
            'period_end': period_end,
            'company_id': self.company_id.id,
            'appraisal_batch_id': self.id,
        })
        return batch._return_form_action()
