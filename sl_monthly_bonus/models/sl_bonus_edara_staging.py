import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def _parse_proxy_date(raw):
    """Best-effort parse of a proxy date value to a date. Returns False on failure."""
    if not raw:
        return False
    try:
        return fields.Date.to_date(raw)
    except Exception:  # noqa: BLE001
        # Tolerate ISO datetimes like '2026-04-01T00:00:00'
        try:
            return fields.Date.to_date(str(raw)[:10])
        except Exception:  # noqa: BLE001
            return False


def _parse_proxy_dt(raw):
    """Best-effort parse of a proxy datetime value. Returns False on failure."""
    if not raw:
        return False
    text = str(raw).replace('T', ' ')
    if len(text) > 19:
        text = text[:19]
    try:
        return fields.Datetime.to_datetime(text)
    except Exception:  # noqa: BLE001
        return False


class SlBonusEdaraStagingMixin(models.AbstractModel):
    """Shared Edara-metadata fields + idempotent proxy ingestion.

    Concrete staging models inherit this for the proxy bookkeeping fields
    (``edara_row_uid``, ``mapping_status`` …) while keeping their own
    calculation-facing fields (``date``, ``amount`` …) untouched so the
    calculator never needs to change.
    """
    _name = 'sl.bonus.edara.staging.mixin'
    _description = 'Edara Staging Mixin'

    # ── Proxy bookkeeping (added by P1 Edara integration) ──────────────
    edara_row_uid = fields.Char(
        string='Edara Row UID', index=True, copy=False,
        help='Stable per-row identifier supplied by the Edara proxy. Used for '
             'idempotent upsert so re-syncing a month creates no duplicates.',
    )
    edara_employee_id = fields.Char(string='Edara Employee ID')
    employee_code = fields.Char(string='Employee Code')
    branch_code = fields.Char(string='Branch Code')
    branch_name = fields.Char(string='Branch Name')
    source_report = fields.Char(string='Source Report')
    last_updated_at = fields.Datetime(string='Edara Last Updated')
    mapping_status = fields.Selection([
        ('mapped', 'Mapped'),
        ('unmapped', 'Unmapped'),
    ], string='Mapping Status', default='mapped', index=True,
        help='Unmapped operational rows are retained for audit but are NEVER '
             'used in bonus calculation until an employee mapping exists.')
    mapping_reason = fields.Char(string='Mapping Note')

    _sql_constraints = [
        ('uniq_edara_row_uid',
         'unique(edara_row_uid)',
         'This Edara row UID already exists (idempotency guard).'),
    ]

    # ── To be provided by concrete models ──────────────────────────────
    def _proxy_role(self):
        raise NotImplementedError

    def _proxy_row_to_vals(self, row, sync):
        raise NotImplementedError

    def _proxy_period_date(self, row, sync):
        d = _parse_proxy_date(row.get('period') or row.get('date') or row.get('period_start'))
        if d:
            return d
        if sync and sync.period_from:
            return sync.period_from
        return fields.Date.context_today(self)

    # ── Idempotent ingestion ───────────────────────────────────────────
    @api.model
    def _ingest_proxy_rows(self, rows, sync, dry_run=False):
        """Upsert proxy rows by ``edara_row_uid``. Returns a counts dict.

        Unmapped rows are kept with ``employee_id`` empty + ``mapping_status``
        'unmapped' + a reason (never used by the calculator). A row missing
        ``edara_row_uid`` aborts the whole scope (no partial ingest).
        """
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        role = self._proxy_role()
        received = len(rows or [])
        created = updated = unmapped = 0
        for row in (rows or []):
            uid = str(row.get('edara_row_uid') or '').strip()
            if not uid:
                raise ValidationError(_(
                    "An Edara '%s' row is missing the required 'edara_row_uid'. "
                    "Aborting this scope (no partial ingest)."
                ) % self._description)
            vals = self._proxy_row_to_vals(row, sync)
            vals['edara_row_uid'] = uid
            vals['sync_id'] = sync.id if sync else False
            edara_emp = vals.get('edara_external_id') or vals.get('edara_employee_id')
            emp = Mapping.resolve_employee(edara_emp, role) if edara_emp else self.env['hr.employee'].browse()
            if emp:
                vals.update({
                    'employee_id': emp.id,
                    'mapping_status': 'mapped',
                    'mapping_reason': False,
                })
            else:
                vals.update({
                    'employee_id': False,
                    'mapping_status': 'unmapped',
                    'mapping_reason': _("No Edara mapping for external id '%s' (role: %s).")
                    % (edara_emp or '?', role),
                })
                unmapped += 1
            if dry_run:
                continue
            existing = self.sudo().search([('edara_row_uid', '=', uid)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.sudo().create(vals)
                created += 1
        return {
            'received': received, 'created': created, 'updated': updated,
            'skipped': 0, 'unmapped': unmapped,
        }


class SlBonusEdaraStagingSales(models.Model):
    """Staging table for collected sales (per salesperson)."""
    _name = 'sl.bonus.edara.staging.sales'
    _inherit = 'sl.bonus.edara.staging.mixin'
    _description = 'Edara Staging — Sales'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference')
    edara_external_id = fields.Char(string='Edara ID (Salesperson)')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    sales_person_name = fields.Char(string='Salesperson Name (Edara)')
    department_code = fields.Char(string='Department Code')
    date = fields.Date(string='Invoice Date', required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    proxy_target_amount = fields.Monetary(
        string='Target (from Edara)', currency_field='currency_id',
        help='Informational target reported alongside achieved sales (if any). '
             'NOT used for calculation — the authoritative target is sl.bonus.target.',
    )
    transaction_count = fields.Integer(string='Transaction Count')
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

    # ── Proxy ingestion hooks ──────────────────────────────────────────
    def _proxy_role(self):
        return 'sales'

    def _proxy_row_to_vals(self, row, sync):
        edara_emp = str(row.get('edara_employee_id') or row.get('employee_code') or '') or False
        return {
            'edara_external_id': edara_emp,
            'edara_employee_id': str(row.get('edara_employee_id') or '') or False,
            'employee_code': row.get('employee_code') or False,
            'sales_person_name': row.get('sales_person_name') or False,
            'department_code': row.get('department_code') or False,
            'branch_code': row.get('branch_code') or False,
            'branch_name': row.get('branch_name') or False,
            'date': self._proxy_period_date(row, sync),
            'amount': float(row.get('achieved_sales_amount') or 0.0),
            'proxy_target_amount': float(row.get('target_amount') or 0.0),
            'transaction_count': int(row.get('transaction_count') or 0),
            'is_collected': True,
            'source_report': row.get('source_report') or False,
            'last_updated_at': _parse_proxy_dt(row.get('last_updated_at')),
        }


class SlBonusEdaraStagingStock(models.Model):
    """Staging table for stock purchase sales (per responsible)."""
    _name = 'sl.bonus.edara.staging.stock'
    _inherit = 'sl.bonus.edara.staging.mixin'
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
    product_group = fields.Char(string='Product Group / Category')
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

    def _proxy_role(self):
        return 'stock_purchasing'

    def _proxy_row_to_vals(self, row, sync):
        edara_emp = str(row.get('edara_employee_id') or row.get('employee_code') or '') or False
        return {
            'edara_external_id': edara_emp,
            'edara_employee_id': str(row.get('edara_employee_id') or '') or False,
            'employee_code': row.get('employee_code') or False,
            'branch_code': row.get('branch_code') or False,
            'branch_name': row.get('branch_name') or False,
            'date': self._proxy_period_date(row, sync),
            'stock_sales_value': float(row.get('stock_purchase_related_sales_value') or 0.0),
            'product_group': row.get('product_group') or row.get('category') or False,
            'source_report': row.get('source_report') or False,
            'last_updated_at': _parse_proxy_dt(row.get('last_updated_at')),
        }


class SlBonusEdaraStagingInstallation(models.Model):
    """Staging table for installation activity (per technician/supervisor)."""
    _name = 'sl.bonus.edara.staging.installation'
    _inherit = 'sl.bonus.edara.staging.mixin'
    _description = 'Edara Staging — Installations'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference')
    edara_external_id = fields.Char(string='Edara ID (Technician)')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    date = fields.Date(string='Installation Date', required=True)
    completed = fields.Boolean(string='Completed', default=True)
    installation_count = fields.Integer(string='Installation Count')
    installation_value = fields.Monetary(
        string='Installation Value', currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
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
                rec.employee_id = Mapping.resolve_employee(rec.edara_external_id, 'installation')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._resolve_employee()
        return records

    def _proxy_role(self):
        return 'installation'

    def _proxy_row_to_vals(self, row, sync):
        edara_emp = str(row.get('edara_employee_id') or row.get('employee_code') or '') or False
        return {
            'edara_external_id': edara_emp,
            'edara_employee_id': str(row.get('edara_employee_id') or '') or False,
            'employee_code': row.get('employee_code') or False,
            'branch_code': row.get('branch_code') or False,
            'branch_name': row.get('branch_name') or False,
            'date': self._proxy_period_date(row, sync),
            'completed': True,
            'installation_count': int(row.get('installation_count') or 0),
            'installation_value': float(row.get('installation_value') or 0.0),
            'source_report': row.get('source_report') or False,
            'last_updated_at': _parse_proxy_dt(row.get('last_updated_at')),
        }
