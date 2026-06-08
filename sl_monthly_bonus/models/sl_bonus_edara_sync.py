import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SlBonusEdaraSync(models.Model):
    """Log of Edara sync runs (manual or scheduled).

    Local-only: no real Edara HTTP call is performed unless configuration
    parameter sl_monthly_bonus.edara_endpoint is set AND
    sl_monthly_bonus.edara_enabled is true. By default both are unset.
    """
    _name = 'sl.bonus.edara.sync'
    _description = 'Edara Sync Run'
    _order = 'started_at desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    started_at = fields.Datetime(
        string='Started At', required=True, default=fields.Datetime.now, readonly=True,
    )
    finished_at = fields.Datetime(string='Finished At', readonly=True)
    triggered_by = fields.Selection([
        ('manual', 'Manual (HR)'),
        ('cron', 'Scheduled (Cron)'),
    ], default='manual', required=True)
    state = fields.Selection([
        ('running', 'Running'),
        ('success', 'Success'),
        ('failure', 'Failure'),
        ('skipped', 'Skipped (Disabled)'),
    ], default='running', required=True, readonly=True, tracking=True)
    period_from = fields.Date(string='Period From', readonly=True)
    period_to = fields.Date(string='Period To', readonly=True)
    sales_records = fields.Integer(string='Sales Rows', readonly=True)
    stock_records = fields.Integer(string='Stock Rows', readonly=True)
    installation_records = fields.Integer(string='Installation Rows', readonly=True)
    message = fields.Text(string='Message', readonly=True)
    user_id = fields.Many2one(
        'res.users', default=lambda self: self.env.user, readonly=True,
    )

    # ── P1 proxy metadata (metadata only — NEVER token/headers/raw rows) ──
    run_uid = fields.Char(string='Run UID', index=True, readonly=True,
                          help='Groups all per-scope log records of a single sync run.')
    request_id = fields.Char(string='Request ID', readonly=True)
    endpoint = fields.Char(string='Endpoint', readonly=True)
    data_type = fields.Selection([
        ('employees', 'Employees'),
        ('sales', 'Sales'),
        ('sales_targets', 'Sales Targets'),
        ('stock_purchasing', 'Stock Purchasing'),
        ('installations', 'Installations'),
        ('branch_profitability', 'Branch Profitability'),
        ('all', 'All Scopes'),
    ], string='Scope / Data Type', readonly=True)
    params_summary = fields.Char(string='Params (sanitized)', readonly=True)
    http_status = fields.Char(string='HTTP Status', readonly=True)
    rows_received = fields.Integer(string='Rows Received', readonly=True)
    rows_created = fields.Integer(string='Rows Created', readonly=True)
    rows_updated = fields.Integer(string='Rows Updated', readonly=True)
    rows_skipped = fields.Integer(string='Rows Skipped', readonly=True)
    duration_ms = fields.Integer(string='Duration (ms)', readonly=True)
    warnings_summary = fields.Text(string='Warnings', readonly=True)
    errors_summary = fields.Text(string='Errors', readonly=True)
    dry_run = fields.Boolean(string='Dry Run', readonly=True)

    @api.depends('started_at', 'state', 'triggered_by')
    def _compute_name(self):
        for rec in self:
            ts = rec.started_at and fields.Datetime.to_string(rec.started_at) or ''
            rec.name = f"Edara Sync {ts} [{rec.triggered_by}/{rec.state}]"

    def _is_enabled(self):
        Param = self.env['ir.config_parameter'].sudo()
        return Param.get_param('sl_monthly_bonus.edara_enabled', '0') == '1'

    def _finish(self, state, message='', counts=None):
        self.ensure_one()
        vals = {
            'state': state,
            'finished_at': fields.Datetime.now(),
            'message': message or '',
        }
        if counts:
            vals.update(counts)
        self.sudo().write(vals)

    @api.model
    def sync_now(self, period_from=None, period_to=None, triggered_by='manual'):
        """Run a sync. Local-safe: if Edara is not configured, the run is recorded
        as 'skipped' and no external call is made."""
        period_to = period_to or fields.Date.today()
        period_from = period_from or (period_to - timedelta(days=1))
        run = self.create({
            'period_from': period_from,
            'period_to': period_to,
            'triggered_by': triggered_by,
        })
        try:
            if not run._is_enabled():
                run._finish(
                    'skipped',
                    _('Edara connection is disabled. Enable via System Parameter '
                      "'sl_monthly_bonus.edara_enabled' = '1' once credentials are configured."),
                )
                return run
            # Local mode: actual Edara call is intentionally not implemented here.
            # Real implementation would call an internal RPA endpoint and insert
            # rows into the staging models. We leave a clean extension point.
            notes = run._call_edara(period_from, period_to)
            counts = run._stage_counts()
            run._finish('success', notes or _('Sync completed.'), counts=counts)
        except Exception as e:
            _logger.exception("Edara sync failed")
            run._finish('failure', str(e))
        return run

    # scope -> staging model used by the lightweight (cron / sync_now) path
    _OPERATIONAL_SCOPES = (
        ('sales', 'sl.bonus.edara.staging.sales'),
        ('stock_purchasing', 'sl.bonus.edara.staging.stock'),
        ('installations', 'sl.bonus.edara.staging.installation'),
    )

    def _call_edara(self, period_from, period_to):
        """Real Edara fetch for the lightweight (cron / sync_now) path.

        Fetches the operational scopes for the period and ingests them into
        staging, attributing rows to this run. Lenient per scope: an
        unsupported/disabled/failed scope is recorded in the message and the
        run continues. Richer per-scope logging lives in the sync wizard.
        """
        # Imported lazily so a missing 'requests' lib never breaks module load.
        from odoo.addons.sl_monthly_bonus.services.edara_client import (
            EdaraProxyClient, EdaraConfigMissing, EdaraSchemaError,
        )
        self.ensure_one()
        client = EdaraProxyClient(self.env)
        health = client.health()
        if not health.get('ok'):
            raise UserError(_("Edara health check failed; aborting sync."))
        notes = []
        params = {
            'date_from': fields.Date.to_string(period_from),
            'date_to': fields.Date.to_string(period_to),
        }
        for scope, model_name in self._OPERATIONAL_SCOPES:
            try:
                result = client.fetch(scope, params=dict(params))
                if result.get('status') in ('unsupported', 'disabled'):
                    notes.append(_("%s: %s (0 rows).") % (scope, result['status']))
                    continue
                counts = self.env[model_name].sudo()._ingest_proxy_rows(
                    result.get('rows') or [], self, dry_run=False,
                )
                notes.append(_("%s: %s received, %s created, %s updated, %s unmapped.") % (
                    scope, counts['received'], counts['created'],
                    counts['updated'], counts.get('unmapped', 0)))
            except (EdaraConfigMissing, EdaraSchemaError, UserError) as exc:
                notes.append(_("%s: failed — %s") % (scope, exc))
        return "\n".join(notes)

    def _stage_counts(self):
        self.ensure_one()
        Sales = self.env['sl.bonus.edara.staging.sales'].sudo()
        Stock = self.env['sl.bonus.edara.staging.stock'].sudo()
        Inst = self.env['sl.bonus.edara.staging.installation'].sudo()
        return {
            'sales_records': Sales.search_count([('sync_id', '=', self.id)]),
            'stock_records': Stock.search_count([('sync_id', '=', self.id)]),
            'installation_records': Inst.search_count([('sync_id', '=', self.id)]),
        }

    @api.model
    def cron_sync_nightly(self):
        """Scheduled action — disabled by default. Safe no-op until Edara enabled."""
        today = fields.Date.today()
        yesterday = today - timedelta(days=1)
        return self.sync_now(period_from=yesterday, period_to=today, triggered_by='cron')
