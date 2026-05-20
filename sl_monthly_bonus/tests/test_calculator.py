"""Smoke tests for the deterministic bonus calculation engine.

Mirrors the five examples from Appendix A of the requirements document:
  Service:        10,000 × 20% × 85% = 1,700
  Sales:          (4,000 × 50%) + (4,000 × 50% × 80%) = 3,600
  Stock:          200,000 × 1.5% × 90% = 2,700
  Installation:   1,500 × 95% = 1,425
  Branch manager: 12,000 × 25% × 90% = 2,700
"""
from datetime import date, timedelta
from odoo import fields as odoo_fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestBonusCalculator(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 4, 1)
        cls.period_end = date(2026, 4, 30)
        cls.Calc = cls.env['sl.bonus.calculator']
        cls.company = cls.env.company

    # ── Helpers ───────────────────────────────────────────────────────
    def _make_job(self, name, category):
        return self.env['hr.job'].create({
            'name': name, 'bonus_category': category,
        })

    def _make_employee(self, name, job, wage):
        emp = self.env['hr.employee'].create({
            'name': name, 'job_id': job.id, 'company_id': self.company.id,
        })
        self.env['hr.contract'].create({
            'name': f'Contract {name}', 'employee_id': emp.id,
            'wage': wage, 'state': 'open',
            'date_start': date(2025, 1, 1),
        })
        return emp

    def _finalize_appraisal(self, emp, score):
        # sl_appraisal restricts state and total_score writes. For tests we:
        #   1. create the appraisal,
        #   2. flip state to 'submitted' (the only state where total_score is writable),
        #   3. write total_score via sudo (inverse sets total_score_manual_override=True),
        #   4. flip state to 'hr_finalization'.
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
        return a

    def _make_branch_location(self, name):
        address = self.env['res.partner'].create({'name': f'Addr {name}'})
        return self.env['hr.work.location'].create({
            'name': name, 'address_id': address.id,
        })

    # ── Tests ─────────────────────────────────────────────────────────
    def test_service_example(self):
        job = self._make_job('Test Accountant', 'service')
        self.env['sl.bonus.service.rate'].create({
            'job_id': job.id, 'percentage': 20.0,
            'date_from': date(2025, 1, 1),
        })
        emp = self._make_employee('Service Emp', job, 10000.0)
        self._finalize_appraisal(emp, 85.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertAlmostEqual(result['line_vals']['computed_amount'], 1700.0, places=2)
        self.assertEqual(result['line_vals']['category'], 'service')

    def test_sales_example(self):
        job = self._make_job('Test Sales', 'sales')
        emp = self._make_employee('Sales Emp', job, 5000.0)
        target = self.env['sl.bonus.target'].create({
            'employee_id': emp.id,
            'period_start': self.period_start,
            'target_amount': 100000.0,
            'tier_ids': [
                (0, 0, {'name': 'T1', 'achievement_min': 80.0, 'commission_amount': 2000.0}),
                (0, 0, {'name': 'T2', 'achievement_min': 100.0, 'commission_amount': 3000.0}),
                (0, 0, {'name': 'T3', 'achievement_min': 110.0, 'commission_amount': 4000.0}),
            ],
        })
        # 110% achievement → tier T3 with 4,000 commission
        self.env['sl.bonus.edara.staging.sales'].create({
            'employee_id': emp.id, 'date': date(2026, 4, 15),
            'amount': 110000.0, 'is_collected': True,
        })
        self._finalize_appraisal(emp, 80.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertAlmostEqual(result['line_vals']['tier_commission'], 4000.0, places=2)
        self.assertAlmostEqual(result['line_vals']['achievement_percent'], 110.0, places=2)
        self.assertAlmostEqual(result['line_vals']['computed_amount'], 3600.0, places=2)

    def test_stock_example(self):
        job = self._make_job('Test Stock Buyer', 'stock')
        self.env['sl.bonus.stock.commission.rate'].create({
            'percentage': 1.5, 'date_from': date(2025, 1, 1),
        })
        emp = self._make_employee('Stock Emp', job, 6000.0)
        self.env['sl.bonus.edara.staging.stock'].create({
            'employee_id': emp.id, 'date': date(2026, 4, 10),
            'stock_sales_value': 200000.0,
        })
        self._finalize_appraisal(emp, 90.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertAlmostEqual(result['line_vals']['computed_amount'], 2700.0, places=2)

    def test_installation_example(self):
        job = self._make_job('Test Installer', 'installation')
        self.env['sl.bonus.installation.rate'].create({
            'job_id': job.id, 'fixed_amount': 1500.0,
            'date_from': date(2025, 1, 1),
        })
        emp = self._make_employee('Inst Emp', job, 4000.0)
        self._finalize_appraisal(emp, 95.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertAlmostEqual(result['line_vals']['computed_amount'], 1425.0, places=2)

    def test_branch_manager_example(self):
        job = self._make_job('Test Branch Mgr', 'branch_manager')
        loc = self._make_branch_location('Test Branch X')
        # Branch profit factor 1.2 → base tier → 25%
        bp = self.env['sl.bonus.branch.profit'].create({
            'work_location_id': loc.id,
            'period_start': self.period_start,
            'factor': 1.2,
        })
        bp.action_approve()
        self.env['sl.bonus.branch.manager.rate'].create({
            'job_id': job.id,
            'pct_low': 15.0, 'pct_base': 25.0, 'pct_high': 35.0,
            'date_from': date(2025, 1, 1),
        })
        emp = self._make_employee('BM Emp', job, 12000.0)
        emp.work_location_id = loc.id
        self._finalize_appraisal(emp, 90.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertAlmostEqual(result['line_vals']['branch_manager_pct'], 25.0, places=2)
        self.assertAlmostEqual(result['line_vals']['computed_amount'], 2700.0, places=2)

    def test_probation_exclusion(self):
        job = self._make_job('Probation Service', 'service')
        self.env['sl.bonus.service.rate'].create({
            'job_id': job.id, 'percentage': 20.0,
            'date_from': date(2025, 1, 1),
        })
        emp = self.env['hr.employee'].create({
            'name': 'Prob Emp', 'job_id': job.id, 'company_id': self.company.id,
        })
        self.env['hr.contract'].create({
            'name': 'C', 'employee_id': emp.id, 'wage': 10000.0,
            'state': 'open', 'date_start': date(2026, 1, 1),
            'trial_date_end': date(2026, 6, 30),  # still in trial during April 2026 period
        })
        self._finalize_appraisal(emp, 100.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertTrue(result['line_vals']['is_excluded'])
        self.assertEqual(result['line_vals']['computed_amount'], 0.0)
        self.assertIn('probation', (result['line_vals']['exclusion_reason'] or '').lower())

    def test_quarterly_exclusion(self):
        job = self._make_job('Dept Head', 'service')
        emp = self._make_employee('Q Manager', job, 20000.0)
        emp.bonus_quarterly_exclusion = True
        self._finalize_appraisal(emp, 100.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertTrue(result['line_vals']['is_excluded'])
        self.assertEqual(result['line_vals']['computed_amount'], 0.0)
        self.assertIn('quarterly', (result['line_vals']['exclusion_reason'] or '').lower())

    def test_branch_manager_blocks_without_approved_factor(self):
        job = self._make_job('Branch Mgr Unapproved', 'branch_manager')
        loc = self._make_branch_location('Test Branch Y')
        # Insert factor but DON'T approve
        self.env['sl.bonus.branch.profit'].create({
            'work_location_id': loc.id,
            'period_start': self.period_start,
            'factor': 1.3,
        })
        self.env['sl.bonus.branch.manager.rate'].create({
            'job_id': job.id, 'pct_low': 15.0, 'pct_base': 25.0, 'pct_high': 35.0,
            'date_from': date(2025, 1, 1),
        })
        emp = self._make_employee('Unapproved BM', job, 12000.0)
        emp.work_location_id = loc.id
        self._finalize_appraisal(emp, 90.0)
        result = self.Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertTrue(result['line_vals']['is_excluded'])
        self.assertEqual(result['line_vals']['computed_amount'], 0.0)
