"""Promotion + authority-invariant tests for Edara staging → authoritative models."""
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestEdaraPromotion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.month = date(2026, 4, 1)
        cls.period_end = date(2026, 4, 30)
        cls.emp = cls.env['hr.employee'].create({'name': 'Target Emp'})

    def _make_location(self, name):
        addr = self.env['res.partner'].create({'name': f'Addr {name}'})
        return self.env['hr.work.location'].create({'name': name, 'address_id': addr.id})

    # ── Sales targets: staging → authoritative sl.bonus.target ──────────
    def test_target_promotion_creates_authoritative(self):
        staging = self.env['sl.bonus.edara.staging.target'].create({
            'edara_row_uid': 't1', 'period_start': self.month,
            'edara_employee_id': 'E1', 'employee_id': self.emp.id,
            'target_amount': 4000.0, 'mapping_status': 'mapped',
        })
        staging.action_promote_to_target()
        target = self.env['sl.bonus.target'].search([
            ('employee_id', '=', self.emp.id), ('period_start', '=', self.month)])
        self.assertEqual(len(target), 1)
        self.assertEqual(target.target_amount, 4000.0)
        self.assertTrue(staging.promoted)
        self.assertEqual(staging.promoted_target_id, target)

    def test_target_promotion_is_upsert(self):
        s1 = self.env['sl.bonus.edara.staging.target'].create({
            'edara_row_uid': 't1', 'period_start': self.month,
            'employee_id': self.emp.id, 'target_amount': 4000.0,
        })
        s1.action_promote_to_target()
        s2 = self.env['sl.bonus.edara.staging.target'].create({
            'edara_row_uid': 't2', 'period_start': self.month,
            'employee_id': self.emp.id, 'target_amount': 5000.0,
        })
        s2.action_promote_to_target()
        targets = self.env['sl.bonus.target'].search([
            ('employee_id', '=', self.emp.id), ('period_start', '=', self.month)])
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets.target_amount, 5000.0)

    # ── Branch profitability: staging → DRAFT, never auto-approved ──────
    def test_branch_profit_promotion_creates_draft_only(self):
        loc = self._make_location('Branch Alpha')
        staging = self.env['sl.bonus.edara.staging.branch.profit'].create({
            'edara_row_uid': 'bp1', 'period_start': self.month,
            'branch_name': 'Branch Alpha', 'work_location_id': loc.id,
            'profitability_factor': 1.25,
        })
        staging.action_promote_to_branch_profit()
        bp = self.env['sl.bonus.branch.profit'].search([
            ('work_location_id', '=', loc.id), ('period_start', '=', self.month)])
        self.assertEqual(len(bp), 1)
        self.assertEqual(bp.state, 'draft')
        self.assertEqual(bp.factor, 1.25)
        # Authority invariant: not visible to find_approved until approved.
        self.assertFalse(self.env['sl.bonus.branch.profit'].find_approved(loc.id, self.month))
        # And the existing gate still works.
        bp.action_approve()
        self.assertEqual(bp.state, 'approved')
        self.assertEqual(self.env['sl.bonus.branch.profit'].find_approved(loc.id, self.month), bp)

    def test_branch_profit_ingest_resolves_location(self):
        loc = self._make_location('Branch Beta')
        counts = self.env['sl.bonus.edara.staging.branch.profit']._ingest_proxy_rows([
            {'edara_row_uid': 'bp9', 'branch_name': 'Branch Beta',
             'profitability_factor': 0.9, 'period': '2026-04-01'},
        ], sync=False, dry_run=False)
        self.assertEqual(counts['created'], 1)
        rec = self.env['sl.bonus.edara.staging.branch.profit'].search([('edara_row_uid', '=', 'bp9')])
        self.assertEqual(rec.work_location_id, loc)

    # ── Calculator uses ONLY approved branch profit ─────────────────────
    def test_calc_excluded_with_only_draft_branch_profit(self):
        loc = self._make_location('Branch Gamma')
        job = self.env['hr.job'].create({'name': 'Branch Mgr', 'bonus_category': 'branch_manager'})
        mgr = self.env['hr.employee'].create({
            'name': 'BM', 'job_id': job.id, 'work_location_id': loc.id,
        })
        self.env['hr.contract'].create({
            'name': 'C', 'employee_id': mgr.id, 'wage': 10000.0,
            'state': 'open', 'date_start': date(2024, 1, 1),
        })
        # Promote a DRAFT factor (never approved).
        staging = self.env['sl.bonus.edara.staging.branch.profit'].create({
            'edara_row_uid': 'bpg', 'period_start': self.month,
            'branch_name': 'Branch Gamma', 'work_location_id': loc.id,
            'profitability_factor': 1.1,
        })
        staging.action_promote_to_branch_profit()
        result = self.env['sl.bonus.calculator'].calculate_for_employee(
            mgr, self.month, self.period_end)
        # Draft factor must NOT be usable -> excluded with the missing-factor reason.
        self.assertTrue(result['line_vals'].get('is_excluded'))
        self.assertEqual(result['line_vals'].get('computed_amount'), 0.0)
