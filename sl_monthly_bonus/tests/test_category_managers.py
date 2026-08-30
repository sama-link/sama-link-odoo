"""Tests for the Sales Online / Sales Projects categories and manager groups.

v18.0.2.18.0 added two categories that pay exactly like Sales, each with its
own manager group scoped (batch lines, targets, staging, CSV imports) to the
employees whose JOB carries that category.
"""
import base64
from datetime import date, timedelta

from odoo import fields as odoo_fields
from odoo.tests import TransactionCase, tagged


def _sales_csv(code, ref):
    return (
        "month,employee_code,employee_name,commission_amount,sales_amount,"
        "target_amount,external_ref,note\n"
        "2026-06,%s,Someone,5000,110000,100000,%s,category guard test\n"
    ) % (code, ref)


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestCategoryManagers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 4, 1)
        cls.period_end = date(2026, 4, 30)
        cls.Calc = cls.env['sl.bonus.calculator']

        def make_user(name, login, group_xmlid):
            return cls.env['res.users'].create({
                'name': name, 'login': login,
                'groups_id': [(6, 0, [cls.env.ref(group_xmlid).id])],
            })

        cls.user_sales = make_user(
            'Sales Mgr', 'cat_mgr_sales_test',
            'sl_monthly_bonus.group_bonus_manager')
        cls.user_online = make_user(
            'Online Mgr', 'cat_mgr_online_test',
            'sl_monthly_bonus.group_bonus_manager_online')
        cls.user_projects = make_user(
            'Projects Mgr', 'cat_mgr_projects_test',
            'sl_monthly_bonus.group_bonus_manager_projects')
        cls.user_hr = make_user(
            'HR Mgr', 'cat_mgr_hr_test',
            'sl_monthly_bonus.group_bonus_hr_manager')

        cls.employees = {}
        for cat, code in (('sales', 'CAT-S'), ('sales_online', 'CAT-O'),
                          ('sales_projects', 'CAT-P')):
            job = cls.env['hr.job'].create({
                'name': 'Job %s' % cat, 'bonus_category': cat,
            })
            emp = cls.env['hr.employee'].create({
                'name': 'Emp %s' % cat, 'job_id': job.id, 'barcode': code,
                'company_id': cls.env.company.id,
            })
            cls.env['hr.contract'].create({
                'name': 'Contract %s' % cat, 'employee_id': emp.id,
                'wage': 5000.0, 'state': 'open', 'date_start': date(2025, 1, 1),
            })
            cls.employees[cat] = emp

        # Global commission tiers shared by every sales-formula category.
        cls.env['sl.bonus.sales.tier'].create([
            {'name': 'T1', 'achievement_min': 80.0, 'commission_percent': 2.0},
            {'name': 'T2', 'achievement_min': 100.0, 'commission_percent': 3.0},
            {'name': 'T3', 'achievement_min': 110.0, 'commission_percent': 4.0},
        ])

    # ── helpers ───────────────────────────────────────────────────────
    def _finalize_appraisal(self, emp, score):
        # Same dance as test_calculator: total_score is only writable in
        # 'submitted', and the calculator reads 'hr_finalization'.
        a = self.env['hr.appraisal'].sudo().create({
            'employee_id': emp.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': odoo_fields.Date.today() + timedelta(days=30),
        })
        self.env.cr.execute("UPDATE hr_appraisal SET state='submitted' WHERE id=%s", (a.id,))
        a.invalidate_recordset()
        a.sudo().write({'total_score': score})
        self.env.cr.execute("UPDATE hr_appraisal SET state='hr_finalization' WHERE id=%s", (a.id,))
        a.invalidate_recordset()

    def _prep_sales_data(self, emp):
        self.env['sl.bonus.target'].create({
            'employee_id': emp.id, 'target_amount': 100000.0,
        })
        self.env['sl.bonus.edara.staging.sales'].create({
            'employee_id': emp.id, 'date': date(2026, 4, 15),
            'amount': 110000.0, 'is_collected': True,
        })
        self._finalize_appraisal(emp, 80.0)

    # ── calculation parity ────────────────────────────────────────────
    def test_new_categories_compute_like_sales(self):
        amounts = {}
        for cat, emp in self.employees.items():
            self._prep_sales_data(emp)
            result = self.Calc.calculate_for_employee(
                emp, self.period_start, self.period_end)
            self.assertEqual(result['line_vals']['category'], cat)
            self.assertFalse(result['line_vals'].get('is_excluded'))
            amounts[cat] = result['line_vals']['computed_amount']
        # 110% achievement -> 4% tier of 110,000 = 4,400; half fixed, half
        # scaled by the 80% evaluation -> 2,200 + 1,760 = 3,960 for all three.
        self.assertAlmostEqual(amounts['sales'], 3960.0, places=2)
        self.assertAlmostEqual(amounts['sales_online'], amounts['sales'], places=2)
        self.assertAlmostEqual(amounts['sales_projects'], amounts['sales'], places=2)

    # ── record-rule scoping ───────────────────────────────────────────
    def test_batch_line_rules_scope_by_category(self):
        Line = self.env['sl.bonus.batch.line']
        lines = {}
        for cat, emp in self.employees.items():
            self._prep_sales_data(emp)
            line = Line.create({
                'employee_id': emp.id, 'period_start': self.period_start,
            })
            line.action_compute()
            self.assertEqual(line.category, cat)
            lines[cat] = line
        ids = [l.id for l in lines.values()]
        for cat, user in (('sales', self.user_sales),
                          ('sales_online', self.user_online),
                          ('sales_projects', self.user_projects)):
            visible = Line.with_user(user).search([('id', 'in', ids)])
            self.assertEqual(visible, lines[cat],
                             "%s must see exactly the %s line" % (user.name, cat))
        self.assertEqual(
            len(Line.with_user(self.user_hr).search([('id', 'in', ids)])), 3)

    def test_target_rules_scope_by_category(self):
        Target = self.env['sl.bonus.target']
        targets = {
            cat: Target.create({'employee_id': emp.id, 'target_amount': 1000.0})
            for cat, emp in self.employees.items()
        }
        ids = [t.id for t in targets.values()]
        for cat, user in (('sales', self.user_sales),
                          ('sales_online', self.user_online),
                          ('sales_projects', self.user_projects)):
            visible = Target.with_user(user).search([('id', 'in', ids)])
            self.assertEqual(visible, targets[cat],
                             "%s must manage exactly the %s target" % (user.name, cat))
        self.assertEqual(
            len(Target.with_user(self.user_hr).search([('id', 'in', ids)])), 3)

    # ── CSV import ────────────────────────────────────────────────────
    def _import_wiz(self, user, csv_text):
        return self.env['sl.bonus.csv.import.wizard'].with_user(user).create({
            'import_type': 'sales', 'month': date(2026, 6, 1),
            'file_data': base64.b64encode(csv_text.encode('utf-8')),
            'file_name': 'sales.csv',
        })

    def test_import_type_selection_for_category_managers(self):
        Wizard = self.env['sl.bonus.csv.import.wizard']
        for user in (self.user_online, self.user_projects):
            self.assertEqual(
                Wizard.with_user(user)._selection_import_type(),
                [('sales', 'Sales')])

    def test_import_guard_blocks_other_category(self):
        # The Online manager may not feed rows of a 'sales' employee...
        wiz = self._import_wiz(self.user_online, _sales_csv('CAT-S', 'G-1'))
        wiz.action_import()
        self.assertEqual(wiz.rows_read, 1)
        self.assertEqual(wiz.rows_failed, 1)
        self.assertFalse(self.env['sl.bonus.edara.staging.sales'].sudo().search(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:CAT-S:G-1')]))
        # ...but their own team imports fine.
        wiz2 = self._import_wiz(self.user_online, _sales_csv('CAT-O', 'G-2'))
        wiz2.action_import()
        self.assertEqual(wiz2.rows_created, 1)
        row = self.env['sl.bonus.edara.staging.sales'].sudo().search(
            [('edara_row_uid', '=', 'csv_manual:sales:2026-06:CAT-O:G-2')])
        self.assertEqual(row.employee_id, self.employees['sales_online'])
