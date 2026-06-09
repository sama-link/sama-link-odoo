from odoo import models, fields, api, _


class SlBonusCsvImportLog(models.Model):
    """Audit log of manual CSV imports into the bonus staging models.

    Metadata only — no raw payload, no secrets. One record per import run
    (including dry runs, which are flagged).
    """
    _name = 'sl.bonus.csv.import.log'
    _description = 'Bonus CSV Import Log'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    import_type = fields.Selection([
        ('sales', 'Sales'),
        ('stock_purchasing', 'Stock Purchasing'),
        ('installations', 'Installations'),
        ('sales_targets', 'Sales Targets'),
        ('branch_profitability', 'Branch Profitability'),
    ], string='Import Type', required=True, readonly=True)
    period = fields.Date(string='Month', readonly=True)
    filename = fields.Char(string='File Name', readonly=True)
    dry_run = fields.Boolean(string='Dry Run', readonly=True)
    state = fields.Selection([
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='State', default='done', readonly=True)
    rows_read = fields.Integer(string='Rows Read', readonly=True)
    rows_created = fields.Integer(string='Rows Created', readonly=True)
    rows_updated = fields.Integer(string='Rows Updated', readonly=True)
    rows_skipped = fields.Integer(string='Rows Skipped', readonly=True)
    rows_failed = fields.Integer(string='Rows Failed', readonly=True)
    message = fields.Text(string='Message', readonly=True)
    user_id = fields.Many2one(
        'res.users', string='Created By',
        default=lambda self: self.env.user, readonly=True,
    )

    @api.depends('import_type', 'period', 'dry_run', 'create_date')
    def _compute_name(self):
        for rec in self:
            period = rec.period and rec.period.strftime('%Y-%m') or ''
            tag = _('Dry Run') if rec.dry_run else _('Import')
            rec.name = f"CSV {tag} — {rec.import_type or ''} — {period}"
