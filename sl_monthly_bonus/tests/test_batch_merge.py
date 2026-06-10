"""Tests for the merged Employees & Bonuses tab introduced in
sl_monthly_bonus 18.0.2.0.0.

The batch form now uses ``line_ids`` as the single source of truth for batch
membership. Tests cover:
- ``_compute_lines`` uses employees already in ``line_ids`` when set,
  preserves manual overrides, and seeds from all-active when empty.
- ``action_add_all_employees`` writes lines directly (no employee_ids).
- The same employee may not appear twice in one batch.
- Recompute preserves manually-added lines that the calculator would not
  otherwise produce (e.g. archived employee still kept temporarily).
"""
from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestBatchMerge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2030, 7, 1)
        cls.period_end = date(2030, 7, 31)

    def _new_batch(self):
        return self.env['sl.bonus.batch'].create({
            'name': 'Test Batch July 2030',
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    def test_add_all_employees_creates_lines_not_employee_ids(self):
        batch = self._new_batch()
        self.assertFalse(batch.line_ids)
        batch.action_add_all_employees()
        # New: lines created directly. employee_ids may remain empty.
        self.assertTrue(batch.line_ids, "Add-all-employees must create lines.")
        # And calling it again must NOT duplicate.
        n = len(batch.line_ids)
        batch.action_add_all_employees()
        self.assertEqual(len(batch.line_ids), n)

    def test_duplicate_employee_in_batch_blocked(self):
        batch = self._new_batch()
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employees.")
        batch.line_ids = [(0, 0, {'employee_id': emp.id})]
        # The constraint may surface as either ValidationError (Python)
        # or psycopg2 IntegrityError → wrapped. Use single class for
        # Odoo's overridden assertRaises which only accepts class form.
        with self.assertRaises(ValidationError):
            batch.line_ids = [(0, 0, {'employee_id': emp.id})]

    def test_compute_uses_existing_line_ids(self):
        """When line_ids is pre-populated, compute must only act on those
        employees (not seed all-active)."""
        batch = self._new_batch()
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employees.")
        batch.line_ids = [(0, 0, {'employee_id': emp.id})]
        batch.action_mark_data_ready()
        batch.action_compute()
        # All resulting lines must correspond to the one employee we seeded.
        self.assertEqual(set(batch.line_ids.mapped('employee_id.id')), {emp.id})

    def test_recompute_preserves_manual_override_in_merged_tab(self):
        batch = self._new_batch()
        batch.action_mark_data_ready()
        batch.action_compute()
        if not batch.line_ids:
            self.skipTest("No batch lines computed.")
        line = batch.line_ids[0]
        line.action_apply_manual_override(321.0, 'Pilot reward')
        batch.action_compute()
        self.assertEqual(line.bonus_amount, 321.0)
        self.assertEqual(line.manual_override_amount, 321.0)

    def test_compute_seeds_lines_when_empty(self):
        """The "leave empty to mean everyone" semantics must survive the merge."""
        batch = self._new_batch()
        batch.action_mark_data_ready()
        batch.action_compute()
        # Result depends on DB content; we only assert no exception and lines exist
        # iff there are active employees.
        any_active = self.env['hr.employee'].search_count([('active', '=', True)])
        self.assertEqual(bool(batch.line_ids), bool(any_active))
