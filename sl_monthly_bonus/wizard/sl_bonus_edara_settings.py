import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sl_monthly_bonus.services import edara_client

_logger = logging.getLogger(__name__)

_PARAMS = {
    'edara_enabled': 'sl_monthly_bonus.edara_enabled',
    'edara_base_url': 'sl_monthly_bonus.edara_base_url',
    'edara_timeout': 'sl_monthly_bonus.edara_timeout',
    'edara_retry_count': 'sl_monthly_bonus.edara_retry_count',
    'edara_retry_backoff': 'sl_monthly_bonus.edara_retry_backoff',
    'edara_page_size': 'sl_monthly_bonus.edara_page_size',
}


class SlBonusEdaraSettings(models.TransientModel):
    """Restricted settings panel for the Edara proxy (HR Manager / Admin).

    The token is WRITE-ONLY: it is never loaded back into the form. A masked
    placeholder + ``token_is_set`` flag tells the user whether one is stored.
    """
    _name = 'sl.bonus.edara.settings'
    _description = 'Edara Proxy Settings'

    edara_enabled = fields.Boolean(string='Edara Enabled')
    edara_base_url = fields.Char(string='Base URL', help='No trailing slash.')
    edara_token = fields.Char(
        string='API Token',
        help='Write-only. Leave blank to keep the existing token. '
             'The stored token is never displayed.',
    )
    token_is_set = fields.Boolean(string='Token Configured', readonly=True)
    edara_timeout = fields.Integer(string='Timeout (s)', default=30)
    edara_retry_count = fields.Integer(string='Retry Count', default=2)
    edara_retry_backoff = fields.Float(string='Retry Backoff', default=1.5)
    edara_page_size = fields.Integer(string='Page Size', default=500)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        Param = self.env['ir.config_parameter'].sudo()
        res['edara_enabled'] = Param.get_param('sl_monthly_bonus.edara_enabled', '0') == '1'
        res['edara_base_url'] = Param.get_param('sl_monthly_bonus.edara_base_url', '')
        res['edara_timeout'] = int(Param.get_param('sl_monthly_bonus.edara_timeout', '30') or 30)
        res['edara_retry_count'] = int(Param.get_param('sl_monthly_bonus.edara_retry_count', '2') or 2)
        res['edara_retry_backoff'] = float(Param.get_param('sl_monthly_bonus.edara_retry_backoff', '1.5') or 1.5)
        res['edara_page_size'] = int(Param.get_param('sl_monthly_bonus.edara_page_size', '500') or 500)
        # NEVER load the token back into the form.
        res['token_is_set'] = bool(Param.get_param('sl_monthly_bonus.edara_token'))
        return res

    def _ensure_access(self):
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only HR Manager / Admin can change Edara settings."))

    @api.constrains('edara_timeout')
    def _check_timeout(self):
        for rec in self:
            if rec.edara_timeout and not (5 <= rec.edara_timeout <= 180):
                raise ValidationError(_("Timeout must be between 5 and 180 seconds."))

    def _persist(self):
        self.ensure_one()
        self._ensure_access()
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('sl_monthly_bonus.edara_enabled', '1' if self.edara_enabled else '0')
        Param.set_param('sl_monthly_bonus.edara_base_url', (self.edara_base_url or '').rstrip('/'))
        Param.set_param('sl_monthly_bonus.edara_timeout', str(self.edara_timeout or 30))
        Param.set_param('sl_monthly_bonus.edara_retry_count', str(self.edara_retry_count or 2))
        Param.set_param('sl_monthly_bonus.edara_retry_backoff', str(self.edara_retry_backoff or 1.5))
        Param.set_param('sl_monthly_bonus.edara_page_size', str(self.edara_page_size or 500))
        # Token is only written when the user actually typed one.
        if self.edara_token:
            Param.set_param('sl_monthly_bonus.edara_token', self.edara_token)
            # Drop it from the transient record so it isn't retained in memory/UI.
            self.edara_token = False

    def action_save(self):
        self._persist()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Edara Settings'),
                'message': _('Settings saved.'),
                'type': 'success', 'sticky': False,
            },
        }

    def action_test_connection(self):
        self._persist()
        client = edara_client.EdaraProxyClient(self.env)
        try:
            health = client.health()
        except (edara_client.EdaraConfigMissing, edara_client.EdaraSchemaError, UserError) as exc:
            return self._notify(_('❌ Connection failed: %s') % exc, 'danger')
        if health.get('ok'):
            msg = _('✅ Connected — proxy v%(v)s, %(ms)s ms') % {
                'v': health.get('version') or '?', 'ms': health.get('latency_ms'),
            }
            return self._notify(msg, 'success')
        return self._notify(_('⚠ Degraded — status: %s') % (health.get('status') or '?'), 'warning')

    def _notify(self, message, kind):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Edara Connection Test'),
                'message': message, 'type': kind, 'sticky': kind != 'success',
            },
        }
