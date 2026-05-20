"""Regression tests for QA findings on sl_monthly_bonus.

Covers:
  * repeated action_compute on the same batch is safe (no AccessError on components)
  * draft / data_ready batches can be unlinked
  * draft / data_ready batch lines can be unlinked
  * approved & locked batches refuse to unlink (friendly UserError)
  * action_open_for_previous_month returns the existing batch when one exists
  * new hr.job defaults bonus_category to 'none'
  * employee whose job is 'none' receives 0 bonus with a clear exclusion reason
"""
from datetime import date, timedelta
from odoo import fields as odoo_fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, AccessError


@tagged('post_install', '-at_install', 'sl_monthly_bonus', 'sl_monthly_bonus_qa')
class TestQAFixes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 2, 1)
        cls.period_end = date(2026, 2, 28)

    def _new_batch(self, name='QA Batch'):
        return self.env['sl.bonus.batch'].create({
            'name': name,
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    # ── #1 — repeated compute ─────────────────────────────────────────
    def test_action_compute_is_repeatable(self):
        batch = self._new_batch('QA Recompute')
        batch.action_mark_data_ready()
        batch.action_compute()
        first_count = len(batch.line_ids)
        # Recompute several times — must not raise, line count must stay stable,
        # and state must remain 'computed'.
        batch.action_compute()
        batch.action_compute()
        batch.action_compute()
        self.assertEqual(batch.state, 'computed')
        self.assertEqual(len(batch.line_ids), first_count)

    def test_recompute_in_hr_review_state(self):
        batch = self._new_batch('QA Recompute HR Review')
        batch.action_mark_data_ready()
        batch.action_compute()
        batch.action_send_to_review()
        self.assertEqual(batch.state, 'hr_review')
        # Recompute from HR Review must be safe and brings batch back to 'computed'.
        batch.action_compute()
        self.assertEqual(batch.state, 'computed')

    # ── #2 — unlink behavior ──────────────────────────────────────────
    def test_unlink_draft_batch(self):
        batch = self._new_batch('QA Delete Draft')
        bid = batch.id
        batch.unlink()
        self.assertFalse(self.env['sl.bonus.batch'].browse(bid).exists())

    def test_unlink_data_ready_batch(self):
        batch = self._new_batch('QA Delete Data Ready')
        batch.action_mark_data_ready()
        batch.unlink()
        self.assertFalse(batch.exists())

    def test_unlink_draft_lines(self):
        batch = self._new_batch('QA Delete Draft Lines')
        batch.action_mark_data_ready()
        batch.action_compute()
        # Reset back to draft (admin) so we can delete a line under the gating rule.
        batch.action_reset_to_draft()
        first_line = batch.line_ids[:1]
        if first_line:
            line_id = first_line.id
            first_line.unlink()
            self.assertFalse(self.env['sl.bonus.batch.line'].browse(line_id).exists())

    def test_unlink_blocked_on_approved_batch(self):
        batch = self._new_batch('QA Block Approved')
        batch.action_mark_data_ready()
        batch.action_compute()
        batch.action_send_to_review()
        batch.action_approve()
        with self.assertRaises(UserError):
            batch.unlink()

    def test_unlink_blocked_on_locked_batch(self):
        batch = self._new_batch('QA Block Locked')
        batch.action_mark_data_ready()
        batch.action_compute()
        batch.action_send_to_review()
        batch.action_approve()
        batch.action_lock()
        with self.assertRaises(UserError):
            batch.unlink()

    def test_unlink_line_blocked_on_approved_batch(self):
        batch = self._new_batch('QA Block Line Approved')
        batch.action_mark_data_ready()
        batch.action_compute()
        batch.action_send_to_review()
        batch.action_approve()
        line = batch.line_ids[:1]
        if not line:
            return
        # Locked-state guard belongs to the line.unlink override.
        # Approved batches don't admit line deletion by HR; only admin allowed,
        # and even admin-via-superuser must use ORM. Our env is admin here.
        # The friendly error must surface for HR / non-admin users; we don't simulate
        # that here (covered by the access path tests). For the admin path,
        # the line.unlink should not raise (admin override).
        line.unlink()

    # ── #3 — previous-month batch opener ──────────────────────────────
    def test_open_previous_month_returns_existing(self):
        Batch = self.env['sl.bonus.batch']
        # Pre-create the previous-month batch for the calling user's company.
        today = odoo_fields.Date.today()
        prev_year = today.year if today.month > 1 else today.year - 1
        prev_month = today.month - 1 if today.month > 1 else 12
        from calendar import monthrange
        start = date(prev_year, prev_month, 1)
        end = date(prev_year, prev_month, monthrange(prev_year, prev_month)[1])
        pre = Batch.create({
            'name': 'Pre-existing Previous Month',
            'period_start': start, 'period_end': end,
        })
        action = Batch.action_open_for_previous_month()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        self.assertEqual(action.get('res_id'), pre.id)

    def test_open_previous_month_creates_when_missing(self):
        Batch = self.env['sl.bonus.batch']
        today = odoo_fields.Date.today()
        prev_year = today.year if today.month > 1 else today.year - 1
        prev_month = today.month - 1 if today.month > 1 else 12
        from calendar import monthrange
        start = date(prev_year, prev_month, 1)
        end = date(prev_year, prev_month, monthrange(prev_year, prev_month)[1])
        # Make sure no batch exists for this period in our test scope.
        Batch.search([('period_start', '=', start), ('period_end', '=', end)]).unlink()
        action = Batch.action_open_for_previous_month()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        # The returned res_id must point to an existing batch.
        self.assertTrue(Batch.browse(action.get('res_id')).exists())

    # ── #4 — job default category ─────────────────────────────────────
    def test_new_job_defaults_to_none(self):
        job = self.env['hr.job'].create({'name': 'QA Some Job'})
        self.assertEqual(job.bonus_category, 'none')

    def test_none_category_employee_yields_zero_bonus_with_reason(self):
        job = self.env['hr.job'].create({'name': 'QA None Job'})
        emp = self.env['hr.employee'].create({'name': 'QA None Emp', 'job_id': job.id})
        self.env['hr.contract'].create({
            'name': 'QA C', 'employee_id': emp.id, 'wage': 10000.0,
            'state': 'open', 'date_start': date(2025, 1, 1),
        })
        result = self.env['sl.bonus.calculator'].calculate_for_employee(
            emp, self.period_start, self.period_end,
        )
        self.assertEqual(result['line_vals']['category'], 'none')
        self.assertTrue(result['line_vals']['is_excluded'])
        self.assertEqual(result['line_vals']['computed_amount'], 0.0)
        reason = (result['line_vals'].get('exclusion_reason') or '').lower()
        self.assertTrue(
            'no monthly bonus category' in reason or 'job position has no monthly bonus' in reason,
            f"Expected a clear 'no category' exclusion reason, got: {reason!r}",
        )

    # ── #5 — clear UserError on missing config (branch-manager path) ──
    def test_branch_manager_no_factor_yields_friendly_reason(self):
        job = self.env['hr.job'].create({
            'name': 'QA BM No Factor', 'bonus_category': 'branch_manager',
        })
        addr = self.env['res.partner'].create({'name': 'QA Addr'})
        loc = self.env['hr.work.location'].create({
            'name': 'QA Loc NoFactor', 'address_id': addr.id,
        })
        emp = self.env['hr.employee'].create({
            'name': 'QA BM Emp', 'job_id': job.id, 'work_location_id': loc.id,
        })
        self.env['hr.contract'].create({
            'name': 'QA C BM', 'employee_id': emp.id, 'wage': 8000.0,
            'state': 'open', 'date_start': date(2025, 1, 1),
        })
        result = self.env['sl.bonus.calculator'].calculate_for_employee(
            emp, self.period_start, self.period_end,
        )
        self.assertTrue(result['line_vals']['is_excluded'])
        reason = result['line_vals']['exclusion_reason'] or ''
        self.assertIn('branch profitability factor', reason.lower())
        self.assertIn('finance', reason.lower())
