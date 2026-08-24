"""Employee card "Appraisal & Bonus" tab: eligibility checkboxes and the
two selects, now the single source of truth (the legacy Administrative
Exclude / Evaluation Exceptions configuration lists were removed).

Covers:
  * defaults: eligible + 'scored' / 'appraisal'
  * Bonus Evaluation = Fixed → calculator treats the evaluation as 100%
  * Administrative Score = 'exempt' → appraisal admin score forced to 100%
  * unchecking a box resets its select
  * ineligible employees are refused by the batch / wizards and excluded by
    the calculator with a clear reason
  * ineligible employees are refused on hr.appraisal
"""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sl_monthly_bonus', 'sl_monthly_bonus_eligibility')
class TestEmployeeEligibility(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 3, 1)
        cls.period_end = date(2026, 3, 31)

    def _employee(self, name='Eligibility Emp'):
        emp = self.env['hr.employee'].create({'name': name})
        self.env['hr.contract'].create({
            'name': f'C {name}', 'employee_id': emp.id, 'wage': 10000.0,
            'state': 'open', 'date_start': date(2025, 1, 1),
        })
        return emp

    def _batch(self, name='Eligibility Batch'):
        return self.env['sl.bonus.batch'].create({
            'name': name,
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    # ── defaults ─────────────────────────────────────────────────────
    def test_defaults_are_eligible(self):
        emp = self._employee()
        self.assertTrue(emp.appraisal_eligible)
        self.assertTrue(emp.bonus_eligible)
        self.assertEqual(emp.appraisal_admin_score_mode, 'scored')
        self.assertEqual(emp.bonus_evaluation_mode, 'appraisal')

    # ── bonus evaluation mode drives the calculator directly ────────
    def test_bonus_fixed_skips_evaluation(self):
        emp = self._employee()
        Calc = self.env['sl.bonus.calculator']
        percent, source = Calc._get_evaluation_percent(emp, self.period_start, self.period_end)
        self.assertEqual(percent, 0.0)  # no appraisal at all

        emp.bonus_evaluation_mode = 'fixed'
        percent, source = Calc._get_evaluation_percent(emp, self.period_start, self.period_end)
        self.assertEqual(percent, 100.0)
        self.assertIn('fixed bonus', source.lower())

        emp.bonus_evaluation_mode = 'appraisal'
        percent, _source = Calc._get_evaluation_percent(emp, self.period_start, self.period_end)
        self.assertEqual(percent, 0.0)

    def test_bonus_uncheck_resets_mode(self):
        emp = self._employee()
        emp.bonus_evaluation_mode = 'fixed'
        emp.bonus_eligible = False
        self.assertEqual(emp.bonus_evaluation_mode, 'appraisal')

    # ── admin score mode drives the appraisal scores directly ───────
    def test_admin_score_exempt_forces_100(self):
        emp = self._employee()
        appraisal = self.env['hr.appraisal'].create({
            'employee_id': emp.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': date(2099, 12, 31),
        })
        emp.appraisal_admin_score_mode = 'exempt'
        self.assertTrue(appraisal.admin_score_exempt)
        self.assertEqual(appraisal.admin_score, 100.0)

        emp.appraisal_admin_score_mode = 'scored'
        self.assertFalse(appraisal.admin_score_exempt)

    def test_appraisal_uncheck_resets_mode(self):
        emp = self._employee()
        emp.appraisal_admin_score_mode = 'exempt'
        emp.appraisal_eligible = False
        self.assertEqual(emp.appraisal_admin_score_mode, 'scored')

    # ── enforcement: bonus ───────────────────────────────────────────
    def test_ineligible_employee_refused_by_batch(self):
        emp = self._employee()
        emp.bonus_eligible = False
        batch = self._batch()
        with self.assertRaises(UserError):
            batch._add_employees_to_lines(emp)

    def test_ineligible_employee_not_a_wizard_candidate(self):
        emp = self._employee('Wizard Ineligible')
        emp.bonus_eligible = False
        batch = self._batch('Wizard Batch')
        wiz = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id, 'mode': 'all',
        })
        self.assertNotIn(emp, wiz._candidate_employees())
        wiz.mode = 'specific'
        wiz.employee_ids = [(6, 0, emp.ids)]
        self.assertFalse(wiz._candidate_employees())

    def test_calculator_excludes_ineligible_with_reason(self):
        emp = self._employee()
        emp.bonus_eligible = False
        result = self.env['sl.bonus.calculator'].calculate_for_employee(
            emp, self.period_start, self.period_end,
        )
        self.assertTrue(result['line_vals']['is_excluded'])
        self.assertEqual(result['line_vals']['bonus_amount'], 0.0)
        self.assertIn('not eligible', (result['line_vals']['exclusion_reason'] or '').lower())

    # ── enforcement: appraisal ───────────────────────────────────────
    def test_ineligible_employee_refused_on_appraisal(self):
        emp = self._employee()
        emp.appraisal_eligible = False
        with self.assertRaises(ValidationError):
            self.env['hr.appraisal'].sudo().create({
                'employee_id': emp.id,
                'date_from': self.period_start,
                'date_to': self.period_end,
                'appraisal_deadline': date(2099, 12, 31),
            })
