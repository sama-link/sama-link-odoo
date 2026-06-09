"""Manual CSV Import for the Monthly Bonus module.

Lets HR/Finance load bonus source data from manually-prepared CSV files when the
Edara API is unavailable. Imports into the SAME staging models used by the Edara
proxy path, so the existing calculator and promotion flows are reused unchanged.

Design guarantees:
  * Calculator logic and bonus formulas are NOT touched.
  * Idempotent: deterministic edara_row_uid per logical row -> re-import upserts,
    never duplicates.
  * Dry run validates and reports without writing.
  * Bad rows never crash the run; they are collected as per-row errors.
  * Unmapped employees/branches are retained (where staging supports it) and are
    never used in calculation.
  * Branch profitability lands in DRAFT staging only — never auto-approved.
  * source_report = 'csv_manual' marks every imported row.
"""
import base64
import csv
import io
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Per-type required columns (header validation).
REQUIRED_COLUMNS = {
    'sales': ['month', 'employee_code', 'commission_amount'],
    'stock_purchasing': ['month', 'employee_code', 'related_stock_sales_value'],
    'installations': ['month', 'employee_code', 'installation_count'],
    'sales_targets': ['month', 'employee_code', 'target_amount'],
    'branch_profitability': ['month', 'branch_code', 'profitability_factor'],
}

# Per-type CSV template: header line + one sample row.
TEMPLATES = {
    'sales': (
        'month,employee_code,employee_name,commission_amount,sales_amount,target_amount,external_ref,note',
        '2026-06,E001,Ahmed Ali,5000,100000,80000,SAL-001,Manual June sales',
    ),
    'stock_purchasing': (
        'month,employee_code,employee_name,related_stock_sales_value,external_ref,note',
        '2026-06,E002,Mohamed Hassan,75000,STK-001,Manual stock purchasing sales',
    ),
    'installations': (
        'month,employee_code,employee_name,installation_count,installation_amount,external_ref,note',
        '2026-06,E003,Mostafa Samir,12,,INS-001,Manual installation count',
    ),
    'sales_targets': (
        'month,employee_code,employee_name,target_amount,external_ref,note',
        '2026-06,E001,Ahmed Ali,80000,TGT-001,Manual monthly target',
    ),
    'branch_profitability': (
        'month,branch_code,branch_name,profitability_factor,revenue,cost,profit_amount,external_ref,note',
        '2026-06,BR-01,Cairo Branch,1.10,500000,350000,150000,BRP-001,Manual branch profitability',
    ),
}

SOURCE_TAG = 'csv_manual'


class SlBonusCsvImportError(models.TransientModel):
    _name = 'sl.bonus.csv.import.error.line'
    _description = 'Bonus CSV Import — Row Error'
    _order = 'row_number'

    wizard_id = fields.Many2one('sl.bonus.csv.import.wizard', ondelete='cascade')
    row_number = fields.Integer(string='Row #')
    message = fields.Char(string='Error')
    raw_identifier = fields.Char(string='Raw Identifier')
    mapping_status = fields.Char(string='Mapping')


class SlBonusCsvImportWizard(models.TransientModel):
    _name = 'sl.bonus.csv.import.wizard'
    _description = 'Manual CSV Import'

    import_type = fields.Selection([
        ('sales', 'Sales'),
        ('stock_purchasing', 'Stock Purchasing'),
        ('installations', 'Installations'),
        ('sales_targets', 'Sales Targets'),
        ('branch_profitability', 'Branch Profitability'),
    ], string='Import Type', required=True, default='sales')
    month = fields.Date(
        string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help='Default month used for rows whose "month" cell is empty. '
             'Day is forced to the 1st.',
    )
    file_data = fields.Binary(string='CSV File')
    file_name = fields.Char(string='File Name')
    dry_run = fields.Boolean(string='Dry Run (validate only)', default=True)
    overwrite = fields.Boolean(
        string='Overwrite Existing Rows', default=False,
        help='If a row already exists (same deterministic key), update it. '
             'When off, existing rows are left unchanged and counted as skipped.',
    )

    executed = fields.Boolean(readonly=True)
    rows_read = fields.Integer(string='Rows Read', readonly=True)
    rows_created = fields.Integer(string='Rows Created', readonly=True)
    rows_updated = fields.Integer(string='Rows Updated', readonly=True)
    rows_skipped = fields.Integer(string='Rows Skipped', readonly=True)
    rows_failed = fields.Integer(string='Rows Failed', readonly=True)
    warnings_text = fields.Text(string='Warnings', readonly=True)
    errors_text = fields.Text(string='Errors', readonly=True)
    error_line_ids = fields.One2many(
        'sl.bonus.csv.import.error.line', 'wizard_id', string='Row Errors', readonly=True)

    # ── access ──────────────────────────────────────────────────────────
    # NOTE: do NOT name this `_check_access` — that is a core BaseModel method
    # (check_access -> _check_access(operation)) and overriding it breaks every
    # ACL check (e.g. get_view) with a signature mismatch.
    def _check_import_access(self):
        self.ensure_one()
        is_admin = self.env.user.has_group('base.group_system')
        is_hr = self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
        is_finance = self.env.user.has_group('sl_monthly_bonus.group_bonus_finance')
        if self.import_type == 'branch_profitability':
            if not (is_finance or is_hr or is_admin):
                raise UserError(_("Only Finance / HR Manager / Admin can import branch profitability."))
        else:
            if not (is_hr or is_admin):
                raise UserError(_("Only HR Manager / Admin can import this data type."))

    # ── parsing helpers ─────────────────────────────────────────────────
    def _parse_month(self, raw):
        raw = (raw or '').strip()
        if not raw:
            return self.month
        if len(raw) == 7 and raw[4] == '-':  # YYYY-MM
            year, month = raw.split('-')
            return fields.Date.to_date('%s-%s-01' % (year, month))
        d = fields.Date.to_date(raw)
        if not d:
            raise ValueError(_("Invalid month '%s' (use YYYY-MM or YYYY-MM-DD).") % raw)
        return d.replace(day=1)

    @staticmethod
    def _to_float(raw, label):
        raw = (raw or '').strip()
        if raw == '':
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise ValueError(_("'%(label)s' must be a number, got '%(val)s'.")
                             % {'label': label, 'val': raw})

    @staticmethod
    def _to_int(raw, label):
        raw = (raw or '').strip()
        if raw == '':
            return 0
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            raise ValueError(_("'%(label)s' must be a whole number, got '%(val)s'.")
                             % {'label': label, 'val': raw})

    def _resolve_employee_by_code(self, code):
        code = (code or '').strip()
        if not code:
            return self.env['hr.employee'].browse()
        Emp = self.env['hr.employee'].sudo()
        for field_name in ('barcode', 'identification_id', 'registration_number'):
            if field_name in Emp._fields:
                rec = Emp.search([(field_name, '=', code)], limit=1)
                if rec:
                    return rec
        return Emp.browse()

    @staticmethod
    def _compose_note(parts):
        bits = ['[%s]' % SOURCE_TAG]
        for label, val in parts:
            if val:
                bits.append('%s=%s' % (label, val))
        return '; '.join(bits)

    # ── per-type row -> (model_name, vals, identifier, mapped) ──────────
    def _build_row(self, row, month):
        t = self.import_type
        ref = (row.get('external_ref') or '').strip()
        if t in ('sales', 'stock_purchasing', 'installations', 'sales_targets'):
            code = (row.get('employee_code') or '').strip()
            emp = self._resolve_employee_by_code(code)
            mapped = bool(emp)
            reason = False if mapped else _("No employee matches code '%s'.") % (code or '?')
            identifier = code
            if t == 'sales':
                model = 'sl.bonus.edara.staging.sales'
                vals = {
                    'employee_code': code, 'edara_external_id': False,
                    'employee_id': emp.id if emp else False,
                    'mapping_status': 'mapped' if mapped else 'unmapped',
                    'mapping_reason': reason,
                    'sales_person_name': (row.get('employee_name') or '').strip() or False,
                    'date': month, 'is_collected': True,
                    'amount': self._to_float(row.get('sales_amount'), 'sales_amount'),
                    'proxy_target_amount': self._to_float(row.get('target_amount'), 'target_amount'),
                    'source_report': SOURCE_TAG,
                    'note': self._compose_note([
                        ('commission_amount', (row.get('commission_amount') or '').strip()),
                        ('external_ref', ref),
                        ('note', (row.get('note') or '').strip()),
                    ]),
                }
            elif t == 'stock_purchasing':
                model = 'sl.bonus.edara.staging.stock'
                vals = {
                    'employee_code': code, 'edara_external_id': False,
                    'employee_id': emp.id if emp else False,
                    'mapping_status': 'mapped' if mapped else 'unmapped',
                    'mapping_reason': reason,
                    'date': month,
                    'stock_sales_value': self._to_float(
                        row.get('related_stock_sales_value'), 'related_stock_sales_value'),
                    'source_report': SOURCE_TAG,
                    'note': self._compose_note([
                        ('employee_name', (row.get('employee_name') or '').strip()),
                        ('external_ref', ref),
                        ('note', (row.get('note') or '').strip()),
                    ]),
                }
            elif t == 'installations':
                model = 'sl.bonus.edara.staging.installation'
                vals = {
                    'employee_code': code, 'edara_external_id': False,
                    'employee_id': emp.id if emp else False,
                    'mapping_status': 'mapped' if mapped else 'unmapped',
                    'mapping_reason': reason,
                    'date': month, 'completed': True,
                    'installation_count': self._to_int(row.get('installation_count'), 'installation_count'),
                    'installation_value': self._to_float(row.get('installation_amount'), 'installation_amount'),
                    'source_report': SOURCE_TAG,
                    'note': self._compose_note([
                        ('employee_name', (row.get('employee_name') or '').strip()),
                        ('external_ref', ref),
                        ('note', (row.get('note') or '').strip()),
                    ]),
                }
            else:  # sales_targets
                model = 'sl.bonus.edara.staging.target'
                vals = {
                    'period_start': month,
                    'employee_code': code, 'edara_employee_id': False,
                    'employee_id': emp.id if emp else False,
                    'mapping_status': 'mapped' if mapped else 'unmapped',
                    'mapping_reason': reason,
                    'target_amount': self._to_float(row.get('target_amount'), 'target_amount'),
                    'source_report': SOURCE_TAG,
                }
            return model, vals, identifier, mapped
        # branch_profitability
        branch_code = (row.get('branch_code') or '').strip()
        branch_name = (row.get('branch_name') or '').strip()
        loc = self.env['sl.bonus.edara.staging.branch.profit']._resolve_work_location(
            branch_name, branch_code)
        mapped = bool(loc)
        model = 'sl.bonus.edara.staging.branch.profit'
        vals = {
            'period_start': month,
            'branch_code': branch_code or False,
            'branch_name': branch_name or False,
            'work_location_id': loc.id if loc else False,
            'profitability_factor': self._to_float(row.get('profitability_factor'), 'profitability_factor'),
            'revenue': self._to_float(row.get('revenue'), 'revenue'),
            'cost': self._to_float(row.get('cost'), 'cost'),
            'profit': self._to_float(row.get('profit_amount'), 'profit_amount'),
            'source_report': SOURCE_TAG,
        }
        return model, vals, branch_code, mapped

    def _make_uid(self, identifier, month, ref):
        base = '%s:%s:%s:%s' % (SOURCE_TAG, self.import_type, month.strftime('%Y-%m'), identifier or '?')
        if ref:
            base += ':%s' % ref
        return base

    def _upsert(self, model_name, uid, vals):
        Model = self.env[model_name].sudo()
        existing = Model.search([('edara_row_uid', '=', uid)], limit=1)
        if existing:
            if not self.overwrite:
                return 'skipped'
            if not self.dry_run:
                existing.write(vals)
            return 'updated'
        if not self.dry_run:
            Model.create(dict(vals, edara_row_uid=uid))
        return 'created'

    # ── main actions ────────────────────────────────────────────────────
    def action_import(self):
        self.ensure_one()
        self._check_import_access()
        if not self.file_data:
            raise UserError(_("Please attach a CSV file."))
        try:
            raw = base64.b64decode(self.file_data).decode('utf-8-sig')
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("Could not decode the file as UTF-8: %s") % exc)

        reader = csv.DictReader(io.StringIO(raw))
        headers = [(h or '').strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS[self.import_type] if c not in headers]
        if missing:
            # Help the user spot a type/file mismatch: if the file's columns match
            # a DIFFERENT import type, point that out explicitly.
            hint = ''
            for other, cols in REQUIRED_COLUMNS.items():
                if other != self.import_type and all(c in headers for c in cols):
                    hint = _(" The uploaded file's columns match import type '%s' — "
                             "select that type (set Import Type before importing).") % other
                    break
            raise UserError(_(
                "CSV is missing required column(s) for import type '%(type)s': %(cols)s.%(hint)s"
            ) % {'type': self.import_type, 'cols': ', '.join(missing), 'hint': hint})

        read = created = updated = skipped = failed = 0
        warnings, errors = [], []
        error_vals = []
        seen_uids = set()

        # csv row 1 is the header; data rows start at line 2.
        for index, raw_row in enumerate(reader, start=2):
            row = {(k or '').strip(): (v.strip() if isinstance(v, str) else v)
                   for k, v in raw_row.items() if k}
            if not any((v or '').strip() for v in row.values()):
                continue  # ignore fully-empty rows
            read += 1
            identifier = (row.get('employee_code') or row.get('branch_code') or '').strip()
            try:
                # required-field presence
                for col in REQUIRED_COLUMNS[self.import_type]:
                    if not (row.get(col) or '').strip():
                        raise ValueError(_("Missing required value for '%s'.") % col)
                month = self._parse_month(row.get('month'))
                model_name, vals, identifier, mapped = self._build_row(row, month)
                ref = (row.get('external_ref') or '').strip()
                uid = self._make_uid(identifier, month, ref)
                if uid in seen_uids:
                    skipped += 1
                    warnings.append(_("Row %s: duplicate key in file (%s) — skipped.") % (index, uid))
                    continue
                seen_uids.add(uid)
                outcome = self._upsert(model_name, uid, vals)
                if outcome == 'created':
                    created += 1
                elif outcome == 'updated':
                    updated += 1
                else:
                    skipped += 1
                if not mapped:
                    warnings.append(_("Row %s: unmapped (%s) — retained, excluded from calculation.")
                                    % (index, identifier or '?'))
                    error_vals.append({
                        'row_number': index, 'message': _('Unmapped (kept, not used in calc)'),
                        'raw_identifier': identifier or '', 'mapping_status': 'unmapped',
                    })
            except Exception as exc:  # noqa: BLE001 - collect, never crash the run
                failed += 1
                msg = str(exc)
                errors.append(_("Row %s: %s") % (index, msg))
                error_vals.append({
                    'row_number': index, 'message': msg,
                    'raw_identifier': identifier or '', 'mapping_status': 'error',
                })

        summary = _(
            "%(type)s | dry_run=%(dry)s | read=%(read)s created=%(c)s updated=%(u)s "
            "skipped=%(s)s failed=%(f)s"
        ) % {
            'type': self.import_type, 'dry': self.dry_run, 'read': read,
            'c': created, 'u': updated, 's': skipped, 'f': failed,
        }
        # Audit log (records dry runs too).
        self.env['sl.bonus.csv.import.log'].sudo().create({
            'import_type': self.import_type, 'period': self.month,
            'filename': self.file_name, 'dry_run': self.dry_run,
            'state': 'done' if not failed else 'failed',
            'rows_read': read, 'rows_created': created, 'rows_updated': updated,
            'rows_skipped': skipped, 'rows_failed': failed, 'message': summary,
        })

        self.error_line_ids.unlink()
        self.write({
            'executed': True,
            'rows_read': read, 'rows_created': created, 'rows_updated': updated,
            'rows_skipped': skipped, 'rows_failed': failed,
            'warnings_text': '\n'.join(warnings) or False,
            'errors_text': '\n'.join(errors) or False,
            'error_line_ids': [(0, 0, v) for v in error_vals],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_download_template(self):
        self.ensure_one()
        header, sample = TEMPLATES[self.import_type]
        content = header + '\n' + sample + '\n'
        attachment = self.env['ir.attachment'].create({
            'name': '%s_template.csv' % self.import_type,
            'type': 'binary',
            'datas': base64.b64encode(content.encode('utf-8')),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
