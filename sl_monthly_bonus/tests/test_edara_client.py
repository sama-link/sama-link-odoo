"""Unit tests for the Edara proxy HTTP client (fully mocked, no live network)."""
from unittest import mock

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError

from odoo.addons.sl_monthly_bonus.services import edara_client
from odoo.addons.sl_monthly_bonus.services.edara_client import (
    EdaraProxyClient, EdaraConfigMissing, EdaraSchemaError,
)
from .edara_common import FakeResponse, envelope, make_router

TOKEN = 'super-secret-token-value'


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestEdaraClient(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Param = cls.env['ir.config_parameter'].sudo()
        Param.set_param('sl_monthly_bonus.edara_enabled', '1')
        Param.set_param('sl_monthly_bonus.edara_base_url', 'https://proxy.test')
        Param.set_param('sl_monthly_bonus.edara_token', TOKEN)
        Param.set_param('sl_monthly_bonus.edara_timeout', '5')
        Param.set_param('sl_monthly_bonus.edara_retry_count', '1')
        Param.set_param('sl_monthly_bonus.edara_retry_backoff', '0')
        Param.set_param('sl_monthly_bonus.edara_page_size', '2')

    def _client(self):
        return EdaraProxyClient(self.env)

    def _patch(self, side_effect):
        return mock.patch.object(edara_client.requests, 'request', side_effect=side_effect)

    # ── health ──────────────────────────────────────────────────────────
    def test_health_success(self):
        router = make_router({'health': (200, {'success': True, 'status': 'ok', 'version': '1.2'})})
        with self._patch(router):
            res = self._client().health()
        self.assertTrue(res['ok'])
        self.assertEqual(res['version'], '1.2')

    def test_health_failure(self):
        router = make_router({'health': (500, {'success': False})})
        with self._patch(router):
            with self.assertRaises(UserError):
                self._client().health()

    # ── schema ──────────────────────────────────────────────────────────
    def test_schema_success(self):
        payload = envelope(success=True, data_type='schema')
        payload['data'] = {'sales': {'fields': ['edara_row_uid', 'edara_employee_id', 'achieved_sales_amount']}}
        router = make_router({'schema': (200, payload)})
        with self._patch(router):
            schema = self._client().schema()
        self.assertIn('sales', schema['data'])

    # ── fetch / pagination ──────────────────────────────────────────────
    def test_fetch_sales_success(self):
        rows = [{'edara_row_uid': 's1', 'edara_employee_id': 'E1', 'achieved_sales_amount': 100}]
        router = make_router({'sales': (200, envelope(rows, data_type='sales', total_count=1))})
        with self._patch(router):
            res = self._client().fetch('sales')
        self.assertEqual(len(res['rows']), 1)
        self.assertIsNone(res['status'])

    def test_pagination(self):
        page1 = envelope(
            [{'edara_row_uid': 's1'}, {'edara_row_uid': 's2'}],
            data_type='sales', page=1, page_size=2, total_count=3)
        page2 = envelope(
            [{'edara_row_uid': 's3'}],
            data_type='sales', page=2, page_size=2, total_count=3)
        router = make_router({}, page_responses={'sales': [(200, page1), (200, page2)]})
        with self._patch(router):
            res = self._client().fetch('sales')
        self.assertEqual(len(res['rows']), 3)
        self.assertEqual(res['pages'], 2)

    # ── status discriminators ───────────────────────────────────────────
    def test_status_unsupported(self):
        router = make_router({'sales': (200, envelope([], status='unsupported',
                                                      warnings=['source unsupported'], data_type='sales'))})
        with self._patch(router):
            res = self._client().fetch('sales')
        self.assertEqual(res['status'], 'unsupported')
        self.assertEqual(res['rows'], [])
        self.assertTrue(res['warnings'])

    def test_status_disabled(self):
        router = make_router({'sales': (200, envelope([], status='disabled', data_type='sales'))})
        with self._patch(router):
            res = self._client().fetch('sales')
        self.assertEqual(res['status'], 'disabled')
        self.assertEqual(res['rows'], [])

    # ── failures ────────────────────────────────────────────────────────
    def test_configuration_missing(self):
        router = make_router({'sales': (200, {'success': False,
                                              'errors': [{'code': 'CONFIGURATION_MISSING'}]})})
        with self._patch(router):
            with self.assertRaises(EdaraConfigMissing):
                self._client().fetch('sales')

    def test_missing_required_field_mapping(self):
        router = make_router({'sales': (200, {'success': False,
                                              'errors': [{'code': 'MISSING_REQUIRED_FIELD_MAPPING'}]})})
        with self._patch(router):
            with self.assertRaises(ValidationError):
                self._client().fetch('sales')

    def test_auth_failure_401_hides_token(self):
        router = make_router({'sales': (401, {'success': False})})
        with self._patch(router):
            with self.assertRaises(UserError) as cm:
                self._client().fetch('sales')
        # The token must NEVER appear in the surfaced error.
        self.assertNotIn(TOKEN, str(cm.exception))

    def test_timeout_retries_then_raises(self):
        calls = {'n': 0}

        def _raise(*a, **k):
            calls['n'] += 1
            raise edara_client.requests.exceptions.Timeout()

        with self._patch(_raise):
            with self.assertRaises(UserError):
                self._client().fetch('sales')
        # retry_count=1 -> 2 attempts total
        self.assertEqual(calls['n'], 2)

    def test_malformed_rows_instead_of_data(self):
        router = make_router({'sales': (200, {'success': True, 'rows': [{'x': 1}]})})
        with self._patch(router):
            with self.assertRaises(ValidationError):
                self._client().fetch('sales')

    def test_malformed_non_json(self):
        def _router(*a, **k):
            return FakeResponse(200, None, raise_json=True)
        with self._patch(_router):
            with self.assertRaises(ValidationError):
                self._client().fetch('sales')
