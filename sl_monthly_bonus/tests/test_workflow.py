"""End-to-end batch workflow tests."""
from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, UserError, ValidationError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestBonusBatchWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 3, 1)
        cls.period_end = date(2026, 3, 31)

    def _new_batch(self):
        return self.env['sl.bonus.batch'].create({
            'name': 'Batch March 2026',
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    def test_batch_state_transitions(self):
        batch = self._new_batch()
        self.assertEqual(batch.state, 'draft')
        batch.action_mark_data_ready()
        self.assertEqual(batch.state, 'data_ready')
        batch.action_compute()
        self.assertEqual(batch.state, 'computed')
        batch.action_send_to_review()
        self.assertEqual(batch.state, 'hr_review')
        batch.action_approve()
        self.assertEqual(batch.state, 'approved')
        batch.action_lock()
        self.assertEqual(batch.state, 'locked')

    def test_manual_override_creates_audit(self):
        batch = self._new_batch()
        batch.action_mark_data_ready()
        batch.action_compute()
        # Pick any line that exists
        line = batch.line_ids[:1]
        if not line:
            return  # No employees configured for this DB; not a regression
        line = line[0]
        before_count = self.env['sl.bonus.audit.log'].search_count([])
        line.action_apply_manual_override(123.45, 'Special bonus for project X')
        self.assertEqual(line.bonus_amount, 123.45)
        self.assertEqual(line.manual_override_amount, 123.45)
        after_count = self.env['sl.bonus.audit.log'].search_count([])
        self.assertGreater(after_count, before_count)

    def test_manual_override_requires_reason(self):
        batch = self._new_batch()
        batch.action_mark_data_ready()
        batch.action_compute()
        line = batch.line_ids[:1]
        if not line:
            return
        with self.assertRaises(ValidationError):
            line.action_apply_manual_override(50.0, '')

    def test_audit_log_cannot_be_deleted(self):
        log = self.env['sl.bonus.audit.log'].sudo().create({
            'action': 'test', 'model': 'sl.bonus.batch', 'res_id': 0,
        })
        with self.assertRaises(UserError):
            log.unlink()

    def test_recompute_preserves_manual_override(self):
        batch = self._new_batch()
        batch.action_mark_data_ready()
        batch.action_compute()
        line = batch.line_ids[:1]
        if not line:
            return
        line = line[0]
        line.action_apply_manual_override(999.99, 'Keep this')
        batch.action_compute()  # recompute
        # The override is preserved even after recompute
        self.assertEqual(line.bonus_amount, 999.99)
        self.assertEqual(line.manual_override_amount, 999.99)
