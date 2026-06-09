"""Tests for the Manual CSV Import wizard."""
import base64
from datetime import date

from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, AccessError

SALES_CSV = (
    "month,employee_code,employee_name,commission_amount,sales_amount,target_amount,external_ref,note\n"
    "2026-06,E001,Ahmed Ali,5000,100000,80000,SAL-001,Manual June sales\n"
)
SALES_CSV_UNKNOWN = (
    "month,employee_code,employee_name,commission_amount,sales_amount,target_amount,external_ref,note\n"
    "2026-06,E999,Ghost,5000,100000,80000,SAL-X,Unknown emp\n"
)
BRANCH_CSV = (
    "month,branch_code,branch_name,profitability_factor,revenue,cost,profit_amount,external_ref,note\n"
    "2026-06,BR-01,Cairo Branch,1.10,500000,350000,150000,BRP-001,Manual\n"
)


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestCsvImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.month = date(2026, 6, 1)
        cls.emp = cls.env['hr.employee'].create({'name': 'Ahmed Ali', 'barcode': 'E001'})
        addr = cls.env['res.partner'].create({'name': 'Cairo Addr'})
        cls.loc = cls.env['hr.work.location'].create({'name': 'Cairo Branch', 'address_id': addr.id})

    def _wiz(self, import_type, csv_text=None, **vals):
        v = {'import_type': import_type, 'month': self.month}
        if csv_text is not None:
            v['file_data'] = base64.b64encode(csv_text.encode('utf-8'))
            v['file_name'] = '%s.csv' % import_type
        v.update(vals)
        return self.env['sl.bonus.csv.import.wizard'].create(v)

    # 1 — template download
    def test_template_download_returns_valid_csv_headers(self):
        wiz = self._wiz('sales')
        action = wiz.action_download_template()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        att_id = int(action['url'].split('/web/content/')[1].split('?')[0])
        att = self.env['ir.attachment'].browse(att_id)
        content = base64.b64decode(att.datas).decode('utf-8')
        first_line = content.splitlines()[0]
        for col in ('month', 'employee_code', 'commission_amount'):
            self.assertIn(col, first_line)

    # 2 — dry run writes nothing
    def test_dry_run_validates_without_writing(self):
        wiz = self._wiz('sales', SALES_CSV, dry_run=True)
        wiz.action_import()
        self.assertEqual(wiz.rows_read, 1)
        self.assertEqual(wiz.rows_created, 1)  # would-be created
        self.assertEqual(self.env['sl.bonus.edara.staging.sales'].search_count(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:E001:SAL-001')]), 0)
        log = self.env['sl.bonus.csv.import.log'].search([], order='id desc', limit=1)
        self.assertTrue(log.dry_run)

    # 3 — import creates staging row
    def test_import_sales_creates(self):
        wiz = self._wiz('sales', SALES_CSV, dry_run=False)
        wiz.action_import()
        row = self.env['sl.bonus.edara.staging.sales'].search(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:E001:SAL-001')])
        self.assertEqual(len(row), 1)
        self.assertEqual(row.employee_id, self.emp)
        self.assertEqual(row.mapping_status, 'mapped')
        self.assertEqual(row.amount, 100000.0)
        self.assertEqual(row.source_report, 'csv_manual')

    # 4 — re-import does not duplicate
    def test_reimport_no_duplicate(self):
        self._wiz('sales', SALES_CSV, dry_run=False, overwrite=True).action_import()
        wiz2 = self._wiz('sales', SALES_CSV, dry_run=False, overwrite=True)
        wiz2.action_import()
        self.assertEqual(self.env['sl.bonus.edara.staging.sales'].search_count(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:E001:SAL-001')]), 1)
        self.assertEqual(wiz2.rows_created, 0)
        self.assertEqual(wiz2.rows_updated, 1)

    # 5 — unknown employee -> unmapped, excluded from calc query
    def test_unknown_employee_unmapped_excluded(self):
        wiz = self._wiz('sales', SALES_CSV_UNKNOWN, dry_run=False)
        wiz.action_import()
        row = self.env['sl.bonus.edara.staging.sales'].search(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:E999:SAL-X')])
        self.assertEqual(len(row), 1)
        self.assertFalse(row.employee_id)
        self.assertEqual(row.mapping_status, 'unmapped')
        # The calculator only ever filters by employee_id -> unmapped never appears.
        self.assertFalse(self.env['sl.bonus.edara.staging.sales'].search(
            [('employee_id', '!=', False), ('edara_row_uid', '=', 'csv_manual:sales:2026-06:E999:SAL-X')]))

    # 6 — branch profitability never auto-approved
    def test_branch_profit_not_approved(self):
        wiz = self._wiz('branch_profitability', BRANCH_CSV, dry_run=False)
        wiz.action_import()
        staging = self.env['sl.bonus.edara.staging.branch.profit'].search(
            [('edara_row_uid', '=', 'csv_manual:branch_profitability:2026-06:BR-01:BRP-001')])
        self.assertEqual(len(staging), 1)
        self.assertEqual(staging.work_location_id, self.loc)
        # No authoritative branch-profit record created, and nothing approved.
        self.assertFalse(self.env['sl.bonus.branch.profit'].find_approved(self.loc.id, self.month))
        self.assertEqual(self.env['sl.bonus.branch.profit'].search_count(
            [('work_location_id', '=', self.loc.id), ('period_start', '=', self.month)]), 0)

    # 7 — access blocked for normal employee
    def test_access_blocks_employee(self):
        user = self.env['res.users'].create({
            'name': 'Plain Emp', 'login': 'plain_emp_csv_test',
            'groups_id': [(6, 0, [self.env.ref('sl_monthly_bonus.group_bonus_employee').id])],
        })
        wiz = self._wiz('sales', SALES_CSV, dry_run=True)
        with self.assertRaises((UserError, AccessError)):
            wiz.with_user(user).action_import()
