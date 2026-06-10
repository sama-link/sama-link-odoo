"""Tests for the bonus-batch ↔ appraisal-batch binding.

Covers:
- The "Add From Appraisal Batch" wizard sets ``appraisal_batch_id`` on the
  bonus batch on confirm.
- ``_compute_lines`` passes the bound appraisal batch down to the
  calculator, and the calculator restricts its evaluation lookup to that
  batch's appraisals only.
- An employee who is in the bonus batch but has NO appraisal in the
  bound appraisal batch is excluded with a clear Arabic message.
- Re-running the wizard with the SAME appraisal batch is idempotent;
  with a DIFFERENT one it refuses (avoids silent rebinding).
- The two header buttons live in the form `<header>`, not inside the
  Employees & Bonuses tab.
"""
from datetime import date
from lxml import etree
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestAppraisalBatchReference(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Far-future periods so no real DB rows clash.
        cls.period_start = date(2033, 3, 1)
        cls.period_end = date(2033, 3, 31)

    # ── Helpers ───────────────────────────────────────────────────────
    def _bonus_batch(self, name='Bonus Batch 2033-03'):
        return self.env['sl.bonus.batch'].create({
            'name': name,
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    def _appraisal_batch(self, name='Appraisal Batch 2033-03'):
        return self.env['hr.appraisal.batch'].create({
            'name': name,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'date_deadline': date(2033, 4, 30),
        })

    def _appraisal(self, employee, appraisal_batch, state=None, total_score=None):
        """Create an appraisal whose state + total_score we can set freely.

        The host ``sl_appraisal`` module gates direct writes ("Total Score
        can only be edited in Submitted stage") and constrains state
        transitions. For tests we go around the model layer with a direct
        UPDATE: the SQL bypass is safe because (a) we never touch real
        production data — every test runs inside a TransactionCase
        savepoint that gets rolled back, and (b) we're not exercising the
        appraisal lifecycle, just providing fixture rows for the bonus
        calculator to read.
        """
        appr = self.env['hr.appraisal'].create({
            'employee_id': employee.id,
            'appraisal_batch_id': appraisal_batch.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': date(2033, 4, 30),
        })
        updates, params = [], []
        if state is not None:
            updates.append('state = %s')
            params.append(state)
        if total_score is not None:
            updates.append('total_score = %s')
            params.append(float(total_score))
        if updates:
            params.append(appr.id)
            self.env.cr.execute(
                "UPDATE hr_appraisal SET " + ', '.join(updates) + " WHERE id = %s",
                params,
            )
            appr.invalidate_recordset()
        return appr

    # ── 1) Wizard sets the reference ──────────────────────────────────
    def test_wizard_sets_appraisal_batch_reference(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        appr_batch = self._appraisal_batch()
        self._appraisal(emp, appr_batch, state='hr_finalization', total_score=82.0)
        bonus_batch = self._bonus_batch()
        self.assertFalse(bonus_batch.appraisal_batch_id)
        wiz = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id,
            'appraisal_batch_id': appr_batch.id,
        })
        wiz.action_confirm()
        self.assertEqual(bonus_batch.appraisal_batch_id, appr_batch,
                         "Wizard must bind the appraisal batch onto the bonus batch.")
        self.assertIn(emp.id, bonus_batch.line_ids.mapped('employee_id.id'))

    def test_wizard_rejects_rebinding_to_different_batch(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        b1 = self._appraisal_batch('Appraisal Batch A 2033')
        b2 = self._appraisal_batch('Appraisal Batch B 2033')
        self._appraisal(emp, b1)
        self._appraisal(emp, b2)
        bonus_batch = self._bonus_batch()
        # First binding via wizard.
        w1 = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id, 'appraisal_batch_id': b1.id,
        })
        w1.action_confirm()
        self.assertEqual(bonus_batch.appraisal_batch_id, b1)
        # Try to rebind to a different one — should refuse, not silently swap.
        w2 = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id, 'appraisal_batch_id': b2.id,
        })
        with self.assertRaises(UserError):
            w2.action_confirm()
        self.assertEqual(bonus_batch.appraisal_batch_id, b1,
                         "Original binding must survive a failed rebind.")

    def test_wizard_with_same_batch_is_idempotent(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        b = self._appraisal_batch()
        self._appraisal(emp, b)
        bonus_batch = self._bonus_batch()
        w = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id, 'appraisal_batch_id': b.id,
        })
        w.action_confirm()
        n_before = len(bonus_batch.line_ids)
        # Run again with the same appraisal batch — no error, no duplicate.
        w2 = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id, 'appraisal_batch_id': b.id,
        })
        w2.action_confirm()
        self.assertEqual(len(bonus_batch.line_ids), n_before)
        self.assertEqual(bonus_batch.appraisal_batch_id, b)

    # ── 2) Compute uses the reference ─────────────────────────────────
    def test_compute_uses_only_reference_batch(self):
        """When bound, the calculator must look up appraisals INSIDE the
        bound appraisal batch — not in a different batch.

        We assert this via ``evaluation_source``, which the calculator
        stamps with ``"hr.appraisal#<id> (batch <bound.id>)"``. That makes
        the assertion robust against ``total_score`` being computed/stored
        from skill rows (which can't be set directly in tests)."""
        emp = self.env['hr.employee'].search([
            ('active', '=', True),
            ('job_id.bonus_category', '=', 'service'),
        ], limit=1)
        if not emp:
            self.skipTest("No active employee with bonus_category=service.")
        bound_batch = self._appraisal_batch('Bound 2033')
        other_batch = self._appraisal_batch('Other 2033')
        appr_in_bound = self._appraisal(emp, bound_batch, state='hr_finalization')
        self._appraisal(emp, other_batch, state='hr_finalization')
        bonus_batch = self._bonus_batch()
        bonus_batch.appraisal_batch_id = bound_batch
        bonus_batch.line_ids = [(0, 0, {'employee_id': emp.id})]
        bonus_batch.action_mark_data_ready()
        bonus_batch.action_compute()
        line = bonus_batch.line_ids.filtered(lambda l: l.employee_id == emp)
        self.assertTrue(line, "Line must exist for the seeded employee.")
        self.assertFalse(line.is_excluded,
                         "Employee has an appraisal in the bound batch — not excluded.")
        self.assertIn(
            f"batch {bound_batch.id}", line.evaluation_source or '',
            "evaluation_source must point to the bound appraisal batch.",
        )
        self.assertIn(
            f"hr.appraisal#{appr_in_bound.id}", line.evaluation_source or '',
            "evaluation_source must reference the appraisal that lives in the bound batch.",
        )

    def test_compute_excludes_employee_missing_from_reference_batch(self):
        """If a bonus batch is bound to an appraisal batch and an employee in
        the bonus batch has NO appraisal inside that appraisal batch, that
        employee is excluded with a clear Arabic reason."""
        emp_in = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        emp_out = self.env['hr.employee'].search([
            ('active', '=', True), ('id', '!=', emp_in.id),
        ], limit=1)
        if not emp_in or not emp_out:
            self.skipTest("Need 2 active employees.")
        bound_batch = self._appraisal_batch()
        # Only emp_in has an appraisal in the bound batch.
        self._appraisal(emp_in, bound_batch, state='hr_finalization', total_score=88.0)
        bonus_batch = self._bonus_batch()
        bonus_batch.appraisal_batch_id = bound_batch
        bonus_batch.line_ids = [
            (0, 0, {'employee_id': emp_in.id}),
            (0, 0, {'employee_id': emp_out.id}),
        ]
        bonus_batch.action_mark_data_ready()
        bonus_batch.action_compute()
        line_out = bonus_batch.line_ids.filtered(lambda l: l.employee_id == emp_out)
        self.assertTrue(line_out.is_excluded,
                        "Employee missing from the reference appraisal batch must be excluded.")
        self.assertTrue(line_out.exclusion_reason,
                        "Excluded employee must have a reason set.")
        # Reason must be Arabic-friendly and mention the appraisal batch.
        reason = line_out.exclusion_reason
        self.assertIn('دفعة التقييم', reason,
                      "Exclusion reason must mention 'دفعة التقييم' (Arabic for "
                      "'evaluation batch').")
        self.assertIn(bound_batch.name, reason,
                      "Exclusion reason must name the bound appraisal batch.")
        self.assertEqual(line_out.bonus_amount, 0.0)

    def test_independent_line_unaffected_by_appraisal_batch_feature(self):
        """Independent lines never have a batch; the new binding must not
        change their calculator path."""
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        # Create an independent line and compute it. With no appraisal_batch
        # in play, behavior should be identical to before this refinement.
        line = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id,
            'period_start': date(2033, 6, 1),
        })
        line.action_compute()
        self.assertEqual(line.state, 'computed')
        # No exception, no spurious exclusion from the new gate.
        # (Whether evaluation_percent is 0 depends on DB content; we only
        # assert the new code path didn't break the existing behavior.)

    # ── 3) View placement ────────────────────────────────────────────
    def test_add_buttons_live_in_form_header(self):
        """The two add-employees buttons must be in the form <header>, not
        in the Employees & Bonuses tab body."""
        view = self.env.ref('sl_monthly_bonus.view_sl_bonus_batch_form')
        arch = etree.fromstring(view.arch)
        header_buttons = arch.xpath(
            "//header/button[@name='action_open_add_employees_wizard' or "
            "@name='action_open_add_from_appraisal_wizard']"
        )
        self.assertEqual(
            len(header_buttons), 2,
            "Both add-employees buttons must be inside <header>; found %s." % len(header_buttons),
        )
        # Ensure the buttons are NOT also living inside the notebook page.
        page_buttons = arch.xpath(
            "//notebook/page[@name='page_employees_bonuses']//button["
            "@name='action_open_add_employees_wizard' or "
            "@name='action_open_add_from_appraisal_wizard']"
        )
        self.assertEqual(
            len(page_buttons), 0,
            "The old in-tab buttons must be removed; found %s leftover." % len(page_buttons),
        )

    def test_appraisal_batch_id_field_shown_on_form(self):
        view = self.env.ref('sl_monthly_bonus.view_sl_bonus_batch_form')
        arch = etree.fromstring(view.arch)
        fields_named = arch.xpath("//field[@name='appraisal_batch_id']")
        self.assertEqual(
            len(fields_named), 1,
            "appraisal_batch_id must appear exactly once on the batch form.",
        )
