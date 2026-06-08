"""Integration tests for the Edara sync wizard (mocked proxy HTTP)."""
from datetime import date
from unittest import mock

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError

from odoo.addons.sl_monthly_bonus.services import edara_client
from .edara_common import envelope, make_router


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestEdaraSyncWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Param = cls.env['ir.config_parameter'].sudo()
        Param.set_param('sl_monthly_bonus.edara_enabled', '1')
        Param.set_param('sl_monthly_bonus.edara_base_url', 'https://proxy.test')
        Param.set_param('sl_monthly_bonus.edara_token', 'tok')
        Param.set_param('sl_monthly_bonus.edara_retry_count', '0')
        Param.set_param('sl_monthly_bonus.edara_retry_backoff', '0')

        cls.month = date(2026, 4, 1)
        cls.emp1 = cls.env['hr.employee'].create({'name': 'Mapped Emp'})
        cls.env['sl.bonus.edara.mapping'].create({
            'employee_id': cls.emp1.id, 'edara_external_id': 'E1', 'role': 'sales',
        })

    def setUp(self):
        super().setUp()
        # Default: everything OK. Tests mutate self.responses before running.
        schema = envelope(success=True, data_type='schema')
        schema['data'] = {
            'employees': {'fields': ['edara_employee_id', 'employee_code']},
            'sales': {'fields': ['edara_row_uid', 'edara_employee_id', 'achieved_sales_amount', 'branch_code']},
            'sales_targets': {'fields': ['edara_employee_id', 'target_amount']},
            'stock_purchasing': {'fields': ['edara_row_uid', 'edara_employee_id', 'stock_purchase_related_sales_value']},
            'installations': {'fields': ['edara_row_uid', 'edara_employee_id', 'installation_count']},
            'branch_profitability': {'fields': ['branch_code', 'profitability_factor']},
        }
        self.responses = {
            'health': (200, {'success': True, 'status': 'ok', 'version': '1.0'}),
            'schema': (200, schema),
            'sales': (200, envelope([
                {'edara_row_uid': 's1', 'edara_employee_id': 'E1', 'achieved_sales_amount': 1000, 'branch_code': 'B1'},
                {'edara_row_uid': 's2', 'edara_employee_id': 'E2', 'achieved_sales_amount': 500, 'branch_code': 'B1'},
            ], data_type='sales', total_count=2)),
            'stock_purchasing': (200, envelope([
                {'edara_row_uid': 'k1', 'edara_employee_id': 'E1', 'stock_purchase_related_sales_value': 2000},
            ], data_type='stock_purchasing', total_count=1)),
            'installations': (200, envelope([
                {'edara_row_uid': 'i1', 'edara_employee_id': 'E1', 'installation_count': 3},
            ], data_type='installations', total_count=1)),
            'sales_targets': (200, envelope([
                {'edara_employee_id': 'E1', 'target_amount': 4000, 'period': '2026-04-01'},
            ], data_type='sales_targets', total_count=1)),
            'branch_profitability': (200, envelope([
                {'branch_code': 'B1', 'branch_name': 'Main', 'profitability_factor': 1.2, 'period': '2026-04-01'},
            ], data_type='branch_profitability', total_count=1)),
            'employees': (200, envelope([], data_type='employees', total_count=0)),
        }

    def _run(self, **vals):
        base = {
            'month': self.month, 'dry_run': False, 'scope_sales': False,
        }
        base.update(vals)
        wiz = self.env['sl.bonus.edara.sync.wizard'].create(base)
        router = make_router(self.responses)
        with mock.patch.object(edara_client.requests, 'request', side_effect=router):
            return wiz.action_run()

    def _last_log(self, data_type):
        return self.env['sl.bonus.edara.sync'].search(
            [('data_type', '=', data_type)], order='id desc', limit=1)

    # ── ingestion + mapping ─────────────────────────────────────────────
    def test_sales_ingest_and_mapping(self):
        self._run(scope_sales=True)
        Sales = self.env['sl.bonus.edara.staging.sales']
        s1 = Sales.search([('edara_row_uid', '=', 's1')])
        s2 = Sales.search([('edara_row_uid', '=', 's2')])
        self.assertEqual(s1.employee_id, self.emp1)
        self.assertEqual(s1.mapping_status, 'mapped')
        self.assertEqual(s1.amount, 1000)
        self.assertFalse(s2.employee_id)
        self.assertEqual(s2.mapping_status, 'unmapped')
        self.assertTrue(s2.mapping_reason)

    def test_idempotent_upsert(self):
        self._run(scope_sales=True)
        self._run(scope_sales=True)
        Sales = self.env['sl.bonus.edara.staging.sales']
        self.assertEqual(Sales.search_count([('edara_row_uid', 'in', ['s1', 's2'])]), 2)
        log = self._last_log('sales')
        self.assertEqual(log.rows_created, 0)
        self.assertEqual(log.rows_updated, 2)

    def test_dry_run_writes_nothing(self):
        self._run(scope_sales=True, dry_run=True)
        Sales = self.env['sl.bonus.edara.staging.sales']
        self.assertEqual(Sales.search_count([('edara_row_uid', 'in', ['s1', 's2'])]), 0)
        log = self._last_log('sales')
        self.assertEqual(log.rows_received, 2)
        self.assertEqual(log.rows_created, 0)
        self.assertTrue(log.dry_run)

    def test_unmapped_excluded_from_calc_query(self):
        self._run(scope_sales=True)
        Sales = self.env['sl.bonus.edara.staging.sales']
        # The calculator only ever filters by employee_id — unmapped rows can't appear.
        mapped = Sales.search([('employee_id', '=', self.emp1.id), ('edara_row_uid', 'in', ['s1', 's2'])])
        self.assertEqual(mapped.mapped('edara_row_uid'), ['s1'])

    # ── lenient per-scope status handling ───────────────────────────────
    def test_unsupported_continues(self):
        self.responses['stock_purchasing'] = (200, envelope(
            [], status='unsupported', warnings=['n/a'], data_type='stock_purchasing'))
        self._run(scope_sales=True, scope_stock=True)
        self.assertEqual(self.env['sl.bonus.edara.staging.sales'].search_count(
            [('edara_row_uid', '=', 's1')]), 1)
        stock_log = self._last_log('stock_purchasing')
        self.assertEqual(stock_log.state, 'skipped')
        self.assertEqual(stock_log.rows_received, 0)

    def test_configuration_missing_scope_only(self):
        self.responses['installations'] = (200, {'success': False,
                                                 'errors': [{'code': 'CONFIGURATION_MISSING'}]})
        # Not strict -> sales still ingested, installations fails alone.
        self._run(scope_sales=True, scope_installations=True)
        self.assertEqual(self.env['sl.bonus.edara.staging.sales'].search_count(
            [('edara_row_uid', '=', 's1')]), 1)
        self.assertEqual(self._last_log('installations').state, 'failure')

    def test_missing_uid_aborts_scope_no_partial(self):
        self.responses['sales'] = (200, envelope([
            {'edara_employee_id': 'E1', 'achieved_sales_amount': 1000},  # no edara_row_uid
        ], data_type='sales', total_count=1))
        self._run(scope_sales=True)
        self.assertEqual(self.env['sl.bonus.edara.staging.sales'].search_count(
            [('employee_id', '=', self.emp1.id)]), 0)
        self.assertEqual(self._last_log('sales').state, 'failure')

    def test_strict_schema_aborts_run(self):
        # Remove a required field from the schema -> mismatch -> strict abort.
        self.responses['schema'][1]['data']['sales']['fields'] = ['edara_row_uid', 'edara_employee_id']
        with self.assertRaises(ValidationError):
            self._run(scope_sales=True, strict_schema=True)
