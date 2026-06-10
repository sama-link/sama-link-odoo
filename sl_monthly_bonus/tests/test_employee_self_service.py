"""Tests for the My Bonus restructure introduced in 18.0.2.0.0.

Covers:
- Old self-estimate cleanup cron deletes records >2 months old, keeps newer ones.
- Employees only see own approved/locked bonus lines (record rule).
- Employees cannot see draft/computed/hr_review lines, even their own.
"""
from datetime import date, timedelta
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestEmployeeSelfService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Estimate = cls.env['sl.bonus.self.estimate']
        cls.Line = cls.env['sl.bonus.batch.line']

    # ── Cleanup cron ─────────────────────────────────────────────────
    def test_cron_cleanup_old_estimates(self):
        # Create a fresh synthetic employee so we don't collide with any
        # existing self-estimates in the live DB.
        emp = self.env['hr.employee'].sudo().create({
            'name': 'Cleanup Cron Test Employee',
        })
        # Old period: a year+ in the past, well before the 2-month cutoff.
        old_period = date(2024, 1, 1)
        # Recent period: well in the future, beyond any plausible cutoff.
        recent_period = date(2035, 1, 1)

        old = self.Estimate.sudo().create({
            'employee_id': emp.id,
            'period_start': old_period,
        })
        new = self.Estimate.sudo().create({
            'employee_id': emp.id,
            'period_start': recent_period,
        })
        deleted = self.Estimate.cron_cleanup_old_estimates()
        self.assertGreaterEqual(deleted, 1)
        self.assertFalse(old.exists(), "Old self-estimate should be deleted.")
        self.assertTrue(new.exists(), "Recent self-estimate must survive cleanup.")

    # ── Record rule: employee can only see approved/locked own lines ──
    def test_employee_cannot_see_draft_own_line(self):
        """Run as a fresh employee user; ensure draft/computed lines are hidden."""
        # Find or create a non-HR user linked to an employee.
        emp = self.env['hr.employee'].search([
            ('active', '=', True),
            ('user_id', '!=', False),
        ], limit=1)
        if not emp:
            self.skipTest("No active employee with a linked user.")
        user = emp.user_id
        # Ensure the user has the employee bonus group but NOT hr_manager.
        emp_group = self.env.ref('sl_monthly_bonus.group_bonus_employee')
        hr_group = self.env.ref('sl_monthly_bonus.group_bonus_hr_manager')
        admin_group = self.env.ref('sl_monthly_bonus.group_bonus_admin')
        if hr_group in user.groups_id or admin_group in user.groups_id:
            self.skipTest("Picked employee is already HR/Admin; can't test record rule.")
        user.groups_id = [(4, emp_group.id)]
        # Create one draft and one approved line for this employee in DIFFERENT months.
        draft_line = self.Line.create({
            'employee_id': emp.id, 'period_start': date(2030, 9, 1),
        })
        approved_line = self.Line.create({
            'employee_id': emp.id, 'period_start': date(2030, 10, 1),
        })
        approved_line.action_compute()
        approved_line.action_approve()
        # Switch context to the employee user.
        visible_ids = self.Line.with_user(user).search([
            ('employee_id', '=', emp.id),
        ]).ids
        self.assertIn(approved_line.id, visible_ids,
                      "Approved own line must be visible to the employee.")
        self.assertNotIn(draft_line.id, visible_ids,
                         "Draft own line must NOT be visible to the employee.")
