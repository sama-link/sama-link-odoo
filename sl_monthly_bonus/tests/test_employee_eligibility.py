"""Employee card "Appraisal & Bonus" tab: eligibility checkboxes and their
two-way sync with the configuration exception lists.

Covers:
  * Bonus Evaluation = Fixed  ⇄  sl.bonus.evaluation.exception (both ways)
  * Administrative Score = No administrative score  ⇄  appraisal.admin.score.exclude
  * unchecking a box resets its select and drops the list entry
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
        cls.BonusException = cls.env['sl.bonus.evaluation.exception']
        cls.AdminExclude = cls.env['appraisal.admin.score.exclude']

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
        self.assertFalse(self.BonusException.search([('employee_id', '=', emp.id)]))
        self.assertFalse(self.AdminExclude.search([('employee_id', '=', emp.id)]))

    # ── bonus: card → list ───────────────────────────────────────────
    def test_bonus_fixed_creates_exception_and_back(self):
        emp = self._employee()
        emp.bonus_evaluation_mode = 'fixed'
        entry = self.BonusException.search([('employee_id', '=', emp.id)])
        self.assertEqual(len(entry), 1)
        self.assertTrue(self.BonusException.is_exempt(emp))

        emp.bonus_evaluation_mode = 'appraisal'
        self.assertFalse(self.BonusException.search([('employee_id', '=', emp.id)]))
        self.assertFalse(self.BonusException.is_exempt(emp))

    def test_bonus_uncheck_resets_mode_and_drops_exception(self):
        emp = self._employee()
        emp.bonus_evaluation_mode = 'fixed'
        emp.bonus_eligible = False
        self.assertEqual(emp.bonus_evaluation_mode, 'appraisal')
        self.assertFalse(self.BonusException.search([('employee_id', '=', emp.id)]))

    # ── bonus: list → card ───────────────────────────────────────────
    def test_bonus_exception_list_updates_card(self):
        emp = self._employee()
        entry = self.BonusException.create({'employee_id': emp.id})
        self.assertTrue(emp.bonus_eligible)
        self.assertEqual(emp.bonus_evaluation_mode, 'fixed')

        entry.unlink()
        self.assertEqual(emp.bonus_evaluation_mode, 'appraisal')

    def test_bonus_exception_reassign_moves_flag(self):
        emp_a = self._employee('A')
        emp_b = self._employee('B')
        entry = self.BonusException.create({'employee_id': emp_a.id})
        entry.employee_id = emp_b
        self.assertEqual(emp_a.bonus_evaluation_mode, 'appraisal')
        self.assertEqual(emp_b.bonus_evaluation_mode, 'fixed')

    # ── appraisal: card ⇄ list ───────────────────────────────────────
    def test_admin_score_exempt_syncs_both_ways(self):
        emp = self._employee()
        emp.appraisal_admin_score_mode = 'exempt'
        self.assertEqual(len(self.AdminExclude.search([('employee_id', '=', emp.id)])), 1)

        emp.appraisal_admin_score_mode = 'scored'
        self.assertFalse(self.AdminExclude.search([('employee_id', '=', emp.id)]))

        entry = self.AdminExclude.create({'employee_id': emp.id})
        self.assertEqual(emp.appraisal_admin_score_mode, 'exempt')
        entry.unlink()
        self.assertEqual(emp.appraisal_admin_score_mode, 'scored')

    def test_appraisal_uncheck_resets_mode_and_drops_exclude(self):
        emp = self._employee()
        emp.appraisal_admin_score_mode = 'exempt'
        emp.appraisal_eligible = False
        self.assertEqual(emp.appraisal_admin_score_mode, 'scored')
        self.assertFalse(self.AdminExclude.search([('employee_id', '=', emp.id)]))

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
