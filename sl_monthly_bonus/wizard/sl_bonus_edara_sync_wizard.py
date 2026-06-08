import logging
import time
import uuid
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

# Imported as a module so tests can patch EdaraProxyClient on the module object.
from odoo.addons.sl_monthly_bonus.services import edara_client

_logger = logging.getLogger(__name__)

# Fixed ingestion order (employees first so later scopes can resolve mappings).
SCOPE_ORDER = [
    'employees', 'sales', 'sales_targets',
    'stock_purchasing', 'installations', 'branch_profitability',
]

# scope -> proxy endpoint path segment (matches services.edara_client.ENDPOINTS)
SCOPE_ENDPOINT = {
    'employees': 'employees',
    'sales': 'sales',
    'sales_targets': 'sales-targets',
    'stock_purchasing': 'stock-purchasing',
    'installations': 'installations',
    'branch_profitability': 'branch-profitability',
}

# scope -> staging model (employees handled separately into the mapping model)
SCOPE_MODEL = {
    'sales': 'sl.bonus.edara.staging.sales',
    'sales_targets': 'sl.bonus.edara.staging.target',
    'stock_purchasing': 'sl.bonus.edara.staging.stock',
    'installations': 'sl.bonus.edara.staging.installation',
    'branch_profitability': 'sl.bonus.edara.staging.branch.profit',
}

# Required fields per scope for the /schema handshake check.
SCOPE_REQUIRED_FIELDS = {
    'employees': ['edara_employee_id'],
    'sales': ['edara_row_uid', 'edara_employee_id', 'achieved_sales_amount'],
    'sales_targets': ['edara_employee_id', 'target_amount'],
    'stock_purchasing': ['edara_row_uid', 'edara_employee_id', 'stock_purchase_related_sales_value'],
    'installations': ['edara_row_uid', 'edara_employee_id', 'installation_count'],
    'branch_profitability': ['branch_code', 'profitability_factor'],
}


class SlBonusEdaraSyncWizard(models.TransientModel):
    _name = 'sl.bonus.edara.sync.wizard'
    _description = 'Edara Sync Wizard'

    month = fields.Date(
        string='Month', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        help='Day is forced to 1; derives the date range for the run.',
    )
    use_custom_range = fields.Boolean(string='Custom Date Range (advanced)')
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    scope_employees = fields.Boolean(string='Employees / Mapping')
    scope_sales = fields.Boolean(string='Sales', default=True)
    scope_sales_targets = fields.Boolean(string='Sales Targets')
    scope_stock = fields.Boolean(string='Stock Purchasing')
    scope_installations = fields.Boolean(string='Installations')
    scope_branch_profit = fields.Boolean(string='Branch Profitability')
    sync_all = fields.Boolean(string='All Scopes')

    dry_run = fields.Boolean(string='Dry Run (no writes)', default=True)
    page_size = fields.Integer(
        string='Page Size',
        default=lambda self: int(self.env['ir.config_parameter'].sudo().get_param(
            'sl_monthly_bonus.edara_page_size', '500')),
    )
    employee_code = fields.Char(string='Employee Code Filter')
    branch_code = fields.Char(string='Branch Code Filter')
    strict_schema = fields.Boolean(
        string='Strict Schema (abort whole run on any scope failure)', default=False,
    )

    @api.constrains('date_from', 'date_to')
    def _check_range(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_to < rec.date_from:
                raise ValidationError(_("Date To must be on or after Date From."))

    @api.constrains('page_size')
    def _check_page_size(self):
        for rec in self:
            if rec.page_size and not (50 <= rec.page_size <= 2000):
                raise ValidationError(_("Page size must be between 50 and 2000."))

    # ── helpers ────────────────────────────────────────────────────────
    def _effective_range(self):
        self.ensure_one()
        if self.use_custom_range and self.date_from and self.date_to:
            return self.date_from, self.date_to
        month = (self.month or fields.Date.context_today(self)).replace(day=1)
        if month.month == 12:
            nxt = month.replace(year=month.year + 1, month=1)
        else:
            nxt = month.replace(month=month.month + 1)
        # last day of month = day before the first of next month
        return month, nxt - timedelta(days=1)

    def _selected_scopes(self):
        self.ensure_one()
        if self.sync_all:
            return list(SCOPE_ORDER)
        flags = {
            'employees': self.scope_employees,
            'sales': self.scope_sales,
            'sales_targets': self.scope_sales_targets,
            'stock_purchasing': self.scope_stock,
            'installations': self.scope_installations,
            'branch_profitability': self.scope_branch_profit,
        }
        return [s for s in SCOPE_ORDER if flags.get(s)]

    def _is_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'sl_monthly_bonus.edara_enabled', '0') == '1'

    def _schema_fields_for(self, schema, scope):
        """Extract the field name set the proxy schema declares for a scope.

        Tolerant of several plausible schema shapes. Returns a set, or None when
        the schema doesn't describe this scope (cannot prove a mismatch).
        """
        if not isinstance(schema, dict):
            return None
        containers = []
        for key in ('data', 'data_types', 'endpoints', 'schemas'):
            val = schema.get(key)
            if isinstance(val, dict):
                containers.append(val)
        node = None
        for cont in containers:
            if scope in cont:
                node = cont[scope]
                break
            if SCOPE_ENDPOINT[scope] in cont:
                node = cont[SCOPE_ENDPOINT[scope]]
                break
        if node is None:
            return None
        if isinstance(node, dict):
            fields_list = node.get('fields') or node.get('required_fields') or node.get('columns')
        else:
            fields_list = node
        if not isinstance(fields_list, (list, tuple)):
            return None
        names = set()
        for f in fields_list:
            if isinstance(f, str):
                names.add(f)
            elif isinstance(f, dict) and f.get('name'):
                names.add(f['name'])
        return names

    def _check_scope_schema(self, schema, scope):
        declared = self._schema_fields_for(schema, scope)
        if declared is None:
            return  # cannot prove mismatch -> lenient pass
        missing = [f for f in SCOPE_REQUIRED_FIELDS.get(scope, []) if f not in declared]
        if missing:
            raise edara_client.EdaraSchemaError(_(
                "Edara schema for '%(scope)s' is missing required field(s): %(fields)s "
                "(MISSING_REQUIRED_FIELD_MAPPING)."
            ) % {'scope': scope, 'fields': ', '.join(missing)})

    def _params_summary(self, date_from, date_to):
        parts = [
            'date_from=%s' % date_from,
            'date_to=%s' % date_to,
            'page_size=%s' % (self.page_size or ''),
        ]
        if self.employee_code:
            parts.append('employee_code=%s' % self.employee_code)
        if self.branch_code:
            parts.append('branch_code=%s' % self.branch_code)
        parts.append('dry_run=%s' % self.dry_run)
        return ', '.join(parts)

    def _open_scope_log(self, run_uid, scope, date_from, date_to):
        return self.env['sl.bonus.edara.sync'].sudo().create({
            'triggered_by': 'manual',
            'state': 'running',
            'run_uid': run_uid,
            'data_type': scope,
            'endpoint': SCOPE_ENDPOINT.get(scope),
            'params_summary': self._params_summary(date_from, date_to),
            'dry_run': self.dry_run,
            'period_from': date_from,
            'period_to': date_to,
        })

    @staticmethod
    def _summarize(items, limit=10):
        if not items:
            return False
        items = [str(i) for i in items]
        head = items[:limit]
        text = '; '.join(head)
        if len(items) > limit:
            text += _(' … (+%s more)') % (len(items) - limit)
        return text

    # ── employees scope → mapping model ────────────────────────────────
    def _resolve_employee_by_code(self, code):
        if not code:
            return self.env['hr.employee'].browse()
        Emp = self.env['hr.employee'].sudo()
        for field_name in ('barcode', 'identification_id', 'registration_number'):
            if field_name in Emp._fields:
                rec = Emp.search([(field_name, '=', code)], limit=1)
                if rec:
                    return rec
        return Emp.browse()

    def _ingest_employees(self, rows, dry_run):
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        received = len(rows or [])
        created = updated = unmapped = 0
        warnings = []
        for row in (rows or []):
            edara_emp = str(row.get('edara_employee_id') or '') or False
            code = row.get('employee_code')
            if not edara_emp:
                continue
            emp = self._resolve_employee_by_code(code)
            if not emp:
                unmapped += 1
                warnings.append(_("Unresolved employee code '%s' (edara id %s).") % (code or '?', edara_emp))
                continue
            for role in ('sales', 'stock_purchasing', 'installation'):
                if dry_run:
                    continue
                existing = Mapping.search([
                    ('edara_external_id', '=', edara_emp), ('role', '=', role),
                ], limit=1)
                if existing:
                    if existing.employee_id.id != emp.id:
                        existing.write({'employee_id': emp.id})
                        updated += 1
                else:
                    Mapping.create({
                        'employee_id': emp.id, 'edara_external_id': edara_emp, 'role': role,
                    })
                    created += 1
        return {
            'received': received, 'created': created, 'updated': updated,
            'skipped': 0, 'unmapped': unmapped, 'warnings': warnings,
        }

    # ── main entry point ───────────────────────────────────────────────
    def action_run(self):
        self.ensure_one()
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only HR Manager / Admin can run an Edara sync."))
        if not self._is_enabled():
            raise UserError(_(
                "Edara integration is disabled. Enable it under "
                "Bonus → Edara → Edara Settings before syncing."
            ))
        scopes = self._selected_scopes()
        if not scopes:
            raise UserError(_("Select at least one scope to sync."))
        date_from, date_to = self._effective_range()
        run_uid = uuid.uuid4().hex

        client = edara_client.EdaraProxyClient(self.env)
        health = client.health()
        if not health.get('ok'):
            raise UserError(_("Edara health check failed; aborting the sync run."))
        try:
            schema = client.schema()
        except (edara_client.EdaraSchemaError, edara_client.EdaraConfigMissing, UserError):
            if self.strict_schema:
                raise
            schema = None
            _logger.warning("Edara /schema unavailable; proceeding without schema validation.")

        base_params = {
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'page_size': self.page_size or None,
        }
        if self.employee_code:
            base_params['employee_code'] = self.employee_code
        if self.branch_code:
            base_params['branch_code'] = self.branch_code

        for scope in scopes:
            log = self._open_scope_log(run_uid, scope, date_from, date_to)
            t0 = time.time()
            try:
                self._check_scope_schema(schema, scope)
                result = client.fetch(scope, params=dict(base_params))
                duration = int((time.time() - t0) * 1000)
                status = result.get('status')
                if status in ('unsupported', 'disabled'):
                    log._finish('skipped', _("Source %s.") % status, counts={
                        'request_id': result.get('request_id'),
                        'http_status': str(result.get('http_status') or ''),
                        'rows_received': 0,
                        'duration_ms': duration,
                        'warnings_summary': self._summarize(result.get('warnings')),
                    })
                    continue
                if scope == 'employees':
                    counts = self._ingest_employees(result.get('rows') or [], self.dry_run)
                    extra_warn = counts.pop('warnings', [])
                else:
                    counts = self.env[SCOPE_MODEL[scope]].sudo()._ingest_proxy_rows(
                        result.get('rows') or [], log, dry_run=self.dry_run,
                    )
                    extra_warn = []
                duration = int((time.time() - t0) * 1000)
                warn_items = list(result.get('warnings') or []) + list(extra_warn)
                if counts.get('unmapped'):
                    warn_items.append(_("%s unmapped row(s) retained (not used in calc).") % counts['unmapped'])
                log._finish('success', _('Scope completed.'), counts={
                    'request_id': result.get('request_id'),
                    'http_status': str(result.get('http_status') or ''),
                    'rows_received': counts.get('received', 0),
                    'rows_created': counts.get('created', 0),
                    'rows_updated': counts.get('updated', 0),
                    'rows_skipped': counts.get('skipped', 0),
                    'duration_ms': duration,
                    'warnings_summary': self._summarize(warn_items),
                })
            except (edara_client.EdaraConfigMissing, edara_client.EdaraSchemaError,
                    ValidationError, UserError) as exc:
                log._finish('failure', _('Scope failed.'), counts={
                    'duration_ms': int((time.time() - t0) * 1000),
                    'errors_summary': str(exc),
                })
                if self.strict_schema:
                    raise
                continue

        return {
            'type': 'ir.actions.act_window',
            'name': _('Edara Sync Log'),
            'res_model': 'sl.bonus.edara.sync',
            'view_mode': 'list,form',
            'domain': [('run_uid', '=', run_uid)],
            'target': 'current',
        }
