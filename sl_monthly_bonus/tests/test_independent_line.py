"""Tests for the independent (batchless) bonus line workflow introduced in
sl_monthly_bonus 18.0.2.0.0.

Covers:
- Lifecycle: draft → computed → approved → locked, plus reset-to-draft.
- Duplicate prevention across (batch-owned, independent) for the same
  (employee, year-month, company).
- Compute reuses the batch calculator and writes inputs/outputs/components.
- Manual override on an independent line emits an audit log entry.
- Recompute preserves a manual override.
- Buttons that don't apply to a given line shape raise correctly.
"""
from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, AccessError, ValidationError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestIndependentBonusLine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Far-future periods to avoid clashing with real DB batches.
        cls.period_start = date(2030, 4, 1)
        cls.period_end = date(2030, 4, 30)
        # Pick any existing active employee — the calculator runs unmodified.
        cls.employee = cls.env['hr.employee'].search([
            ('active', '=', True),
        ], limit=1)
        # Pick a second distinct employee for the duplicate-cross test.
        cls.employee_2 = cls.env['hr.employee'].search([
            ('active', '=', True),
            ('id', '!=', cls.employee.id),
        ], limit=1)

    def _new_independent(self, employee=None, period_start=None):
        emp = employee or self.employee
        if not emp:
            self.skipTest("No active employee in this DB — independent line tests require one.")
        return self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id,
            'period_start': period_start or self.period_start,
        })

    # ── Lifecycle ────────────────────────────────────────────────────
    def test_create_defaults_to_draft_and_independent(self):
        line = self._new_independent()
        self.assertFalse(line.batch_id)
        self.assertTrue(line.is_independent)
        self.assertEqual(line.state, 'draft')
        # period_end auto-snaps to last day of month.
        self.assertEqual(line.period_start, date(2030, 4, 1))
        self.assertEqual(line.period_end, date(2030, 4, 30))

    def test_full_lifecycle_compute_approve_lock(self):
        line = self._new_independent()
        line.action_compute()
        self.assertEqual(line.state, 'computed')
        # Calculator wrote inputs/outputs (even if amount=0 for excluded employees).
        self.assertTrue(line.category)
        line.action_approve()
        self.assertEqual(line.state, 'approved')
        line.action_lock()
        self.assertEqual(line.state, 'locked')

    def test_reset_to_draft(self):
        line = self._new_independent()
        line.action_compute()
        line.action_approve()
        line.action_reset_to_draft()
        self.assertEqual(line.state, 'draft')

    def test_buttons_reject_batch_owned_lines(self):
        """Independent-line buttons must refuse to act on a batch-owned line."""
        batch = self.env['sl.bonus.batch'].create({
            'name': 'Test Batch April 2030',
            'period_start': date(2030, 4, 1),
            'period_end': date(2030, 4, 30),
        })
        batch.action_mark_data_ready()
        batch.action_compute()
        line = batch.line_ids[:1]
        if not line:
            self.skipTest("No batch lines computed — DB has no eligible employees.")
        with self.assertRaises(UserError):
            line.action_compute()
        with self.assertRaises(UserError):
            line.action_approve()
        with self.assertRaises(UserError):
            line.action_reset_to_draft()

    # ── Duplicate prevention ─────────────────────────────────────────
    def test_duplicate_independent_lines_blocked(self):
        self._new_independent()
        with self.assertRaises(ValidationError):
            self._new_independent()

    def test_independent_blocked_when_employee_in_batch(self):
        """Creating an independent line for an employee already in a batch for
        the same month must raise — duplicate-prevention rule is cross-cutting."""
        batch = self.env['sl.bonus.batch'].create({
            'name': 'Test Batch May 2030',
            'period_start': date(2030, 5, 1),
            'period_end': date(2030, 5, 31),
        })
        batch.action_mark_data_ready()
        batch.action_compute()
        line = batch.line_ids[:1]
        if not line:
            self.skipTest("No batch lines computed — DB has no eligible employees.")
        emp_in_batch = line[0].employee_id
        with self.assertRaises(ValidationError):
            self.env['sl.bonus.batch.line'].create({
                'employee_id': emp_in_batch.id,
                'period_start': date(2030, 5, 15),  # within the same month
            })

    def test_independent_allowed_for_different_month(self):
        line_a = self._new_independent(period_start=date(2030, 4, 1))
        line_b = self.env['sl.bonus.batch.line'].create({
            'employee_id': self.employee.id,
            'period_start': date(2030, 5, 1),
        })
        self.assertTrue(line_a.id)
        self.assertTrue(line_b.id)
        self.assertNotEqual(line_a.period_start, line_b.period_start)

    # ── Manual override on independent line ──────────────────────────
    def test_manual_override_audited_on_independent_line(self):
        line = self._new_independent()
        line.action_compute()
        before = self.env['sl.bonus.audit.log'].search_count([])
        line.action_apply_manual_override(777.0, 'Spot bonus per CEO note')
        self.assertEqual(line.bonus_amount, 777.0)
        self.assertEqual(line.manual_override_amount, 777.0)
        after = self.env['sl.bonus.audit.log'].search_count([])
        self.assertGreater(after, before)

    def test_recompute_preserves_manual_override(self):
        line = self._new_independent()
        line.action_compute()
        line.action_apply_manual_override(555.55, 'Per HR Director')
        # Reset back to draft then recompute — override must survive.
        line.action_reset_to_draft()
        line.action_compute()
        self.assertEqual(line.bonus_amount, 555.55)
        self.assertEqual(line.manual_override_amount, 555.55)

    # ── State propagation from batch ─────────────────────────────────
    def test_batch_state_propagates_to_lines(self):
        batch = self.env['sl.bonus.batch'].create({
            'name': 'Test Batch June 2030',
            'period_start': date(2030, 6, 1),
            'period_end': date(2030, 6, 30),
        })
        batch.action_mark_data_ready()
        batch.action_compute()
        if not batch.line_ids:
            self.skipTest("No batch lines computed — DB has no eligible employees.")
        # After compute, all lines should be in 'computed' state.
        self.assertTrue(all(l.state == 'computed' for l in batch.line_ids))
        batch.action_approve()
        self.assertTrue(all(l.state == 'approved' for l in batch.line_ids))
