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
            run._call_edara(period_from, period_to)
            counts = run._stage_counts()
            run._finish('success', _('Sync completed.'), counts=counts)
        except Exception as e:
            _logger.exception("Edara sync failed")
            run._finish('failure', str(e))
        return run

    def _call_edara(self, period_from, period_to):
        """Hook for actual integration. Subclasses or env config can override."""
        raise UserError(_(
            "Edara live integration is not configured in this environment. "
            "Use the 'Import Edara Data' wizard to load mock/local data."
        ))

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
