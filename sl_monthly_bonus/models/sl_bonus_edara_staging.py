from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SlBonusEdaraStagingSales(models.Model):
    """Staging table for collected sales (per salesperson)."""
    _name = 'sl.bonus.edara.staging.sales'
    _description = 'Edara Staging — Sales'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference')
    edara_external_id = fields.Char(string='Edara ID (Salesperson)')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    date = fields.Date(string='Invoice Date', required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    is_collected = fields.Boolean(
        string='Collected', default=True,
        help='True for collected invoices (counted toward target).',
    )
    sync_id = fields.Many2one('sl.bonus.edara.sync', string='Sync Run', ondelete='set null')
    period_start = fields.Date(string='Month', compute='_compute_period', store=True)
    note = fields.Text(string='Note')

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            rec.period_start = rec.date.replace(day=1) if rec.date else False

    def _resolve_employee(self):
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        for rec in self:
            if not rec.employee_id and rec.edara_external_id:
                rec.employee_id = Mapping.resolve_employee(rec.edara_external_id, 'sales')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._resolve_employee()
        return records


class SlBonusEdaraStagingStock(models.Model):
    """Staging table for stock purchase sales (per responsible)."""
    _name = 'sl.bonus.edara.staging.stock'
    _description = 'Edara Staging — Stock Purchases'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference')
    edara_external_id = fields.Char(string='Edara ID (Responsible)')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    date = fields.Date(string='Date', required=True)
    stock_sales_value = fields.Monetary(
        string='Stock Sales Value',
        required=True, currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    classification = fields.Selection([
        ('po_level', 'Per Purchase Order'),
        ('warehouse_level', 'Per Warehouse'),
    ], default='po_level', string='Stock Classification',
        help='How the stock vs. immediate purchase distinction was made in Edara.')
    sync_id = fields.Many2one('sl.bonus.edara.sync', string='Sync Run', ondelete='set null')
    period_start = fields.Date(string='Month', compute='_compute_period', store=True)
    note = fields.Text(string='Note')

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            rec.period_start = rec.date.replace(day=1) if rec.date else False

    def _resolve_employee(self):
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        for rec in self:
            if not rec.employee_id and rec.edara_external_id:
                rec.employee_id = Mapping.resolve_employee(rec.edara_external_id, 'stock_purchasing')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._resolve_employee()
        return records


class SlBonusEdaraStagingInstallation(models.Model):
    """Staging table for installation activity (per technician/supervisor)."""
    _name = 'sl.bonus.edara.staging.installation'
    _description = 'Edara Staging — Installations'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference')
    edara_external_id = fields.Char(string='Edara ID (Technician)')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    date = fields.Date(string='Installation Date', required=True)
    completed = fields.Boolean(string='Completed', default=True)
    sync_id = fields.Many2one('sl.bonus.edara.sync', string='Sync Run', ondelete='set null')
    period_start = fields.Date(string='Month', compute='_compute_period', store=True)
    note = fields.Text(string='Note')

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            rec.period_start = rec.date.replace(day=1) if rec.date else False

    def _resolve_employee(self):
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        for rec in self:
            if not rec.employee_id and rec.edara_external_id:
                rec.employee_id = Mapping.resolve_employee(rec.edara_external_id, 'installation')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._resolve_employee()
        return records
