"""Regression tests for roadmap milestone features."""
from datetime import date, timedelta
from odoo import fields as odoo_fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install', 'sl_monthly_bonus', 'sl_monthly_bonus_roadmap')
class TestRoadmapFeatures(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.period_start = date(2026, 7, 1)
        cls.period_end = date(2026, 7, 31)

    # ── helpers ────────────────────────────────────────────────────────
    def _new_batch(self, **vals):
        v = {
            'name': vals.get('name', 'RoadmapBatch'),
            'period_start': self.period_start,
            'period_end': self.period_end,
        }
        v.update(vals)
        self.env['sl.bonus.batch'].search([
            ('period_start', '=', v['period_start']),
            ('period_end', '=', v['period_end']),
        ]).unlink()
        return self.env['sl.bonus.batch'].create(v)

    def _make_employee(self, name='RM Emp'):
        emp = self.env['hr.employee'].create({'name': name})
        self.env['hr.contract'].create({
            'name': f'C-{name}', 'employee_id': emp.id, 'wage': 5000.0,
            'state': 'open', 'date_start': date(2025, 1, 1),
        })
        return emp

    # ── Partial compute via wizard ─────────────────────────────────────
    def test_partial_compute_wizard(self):
        batch = self._new_batch(name='RM Partial')
        batch.action_mark_data_ready()
        batch.action_compute()
        sample = batch.line_ids[:2]
        if len(sample) < 1:
            return
        wizard = self.env['sl.bonus.compute.wizard'].create({
            'batch_id': batch.id,
            'scope': 'selected',
            'employee_ids': [(6, 0, sample.mapped('employee_id').ids)],
        })
        self.assertEqual(wizard.affected_count_preview, len(sample))
        wizard.action_run()
        self.assertEqual(batch.state, 'computed')
        self.assertEqual(len(batch.line_ids), batch.line_count)

    def test_partial_compute_requires_employees(self):
        batch = self._new_batch(name='RM PartialEmpty')
        batch.action_mark_data_ready()
        batch.action_compute()
        wizard = self.env['sl.bonus.compute.wizard'].create({
            'batch_id': batch.id, 'scope': 'selected', 'employee_ids': [(6, 0, [])],
        })
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_per_line_recompute_button(self):
        batch = self._new_batch(name='RM LineButton')
        batch.action_mark_data_ready()
        batch.action_compute()
        line = batch.line_ids[:1]
        if not line:
            return
        line.action_compute_this_line()
        line.action_compute_this_line()
        self.assertEqual(batch.state, 'computed')

    # ── Manual admin state change ──────────────────────────────────────
    def test_admin_manual_state_change_audited(self):
        batch = self._new_batch(name='RM StateChange')
        batch.action_mark_data_ready()
        batch.action_compute()
        before = self.env['sl.bonus.audit.log'].search_count([])
        wizard = self.env['sl.bonus.state.change.wizard'].create({
            'batch_id': batch.id,
            'new_state': 'hr_review',
            'reason': 'Recovering after manual fix',
        })
        wizard.action_apply()
        self.assertEqual(batch.state, 'hr_review')
        after = self.env['sl.bonus.audit.log'].search_count([])
        self.assertGreater(after, before)

    def test_admin_manual_state_change_requires_reason(self):
        batch = self._new_batch(name='RM StateChangeNoReason')
        wizard = self.env['sl.bonus.state.change.wizard'].create({
            'batch_id': batch.id, 'new_state': 'computed', 'reason': '   ',
        })
        with self.assertRaises(ValidationError):
            wizard.action_apply()

    # ── Treat missing eval as full ─────────────────────────────────────
    def test_treat_missing_eval_as_full_flag(self):
        emp = self._make_employee('RM Treat100 Emp')
        job = self.env['hr.job'].create({
            'name': 'RM Service', 'bonus_category': 'service',
        })
        self.env['sl.bonus.service.rate'].create({
            'job_id': job.id, 'percentage': 20.0, 'date_from': date(2025, 1, 1),
        })
        emp.job_id = job.id
        Calc = self.env['sl.bonus.calculator']
        r0 = Calc.calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertEqual(r0['line_vals']['evaluation_percent'], 0.0)
        r1 = Calc.with_context(
            sl_bonus_treat_missing_eval_as_full=True,
        ).calculate_for_employee(emp, self.period_start, self.period_end)
        self.assertEqual(r1['line_vals']['evaluation_percent'], 100.0)
        self.assertTrue(r1['line_vals']['eval_treated_as_full'])
        self.assertGreater(r1['line_vals']['computed_amount'], 0.0)

    # ── Appraisal smart button ─────────────────────────────────────────
    def test_appraisal_smart_button_creates_or_opens_bonus_batch(self):
        appraisal_batch = self.env['hr.appraisal.batch'].create({
            'name': 'RM Appraisal Batch',
            'date_from': date(2026, 6, 1),
            'date_to': date(2026, 6, 30),
            'date_deadline': date(2026, 7, 31),
        })
        # Self-clean any stale matching bonus batch.
        self.env['sl.bonus.batch'].search([
            ('period_start', '=', date(2026, 6, 1)),
            ('period_end', '=', date(2026, 6, 30)),
        ]).unlink()
        action = appraisal_batch.action_open_or_create_bonus_batch()
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        bonus_batch = self.env['sl.bonus.batch'].browse(action.get('res_id'))
        self.assertTrue(bonus_batch.exists())
        self.assertEqual(bonus_batch.appraisal_batch_id, appraisal_batch)
        action2 = appraisal_batch.action_open_or_create_bonus_batch()
        self.assertEqual(action2.get('res_id'), bonus_batch.id)

    # ── Job category management ────────────────────────────────────────
    def test_job_category_action_resolves(self):
        action = self.env.ref('sl_monthly_bonus.action_hr_job_bonus_category')
        self.assertEqual(action.res_model, 'hr.job')

    # ── Dashboard model ────────────────────────────────────────────────
    def test_dashboard_model_queryable(self):
        rows = self.env['sl.bonus.dashboard.line'].search([], limit=5)
        self.assertIsInstance(rows.ids, list)

    # ── Reports ────────────────────────────────────────────────────────
    def test_payout_report_renders(self):
        batch = self._new_batch(name='RM PayoutReport')
        batch.action_mark_data_ready()
        batch.action_compute()
        batch.action_send_to_review()
        report = self.env.ref('sl_monthly_bonus.action_report_bonus_payout')
        content, _ct = self.env['ir.actions.report'].sudo()._render_qweb_html(
            report.id, [batch.id],
        )
        self.assertTrue(content and len(content) > 100)
        self.assertIn('Monthly Bonus Payout Sheet', content.decode('utf-8'))

    def test_department_report_renders(self):
        batch = self._new_batch(name='RM DeptReport')
        batch.action_mark_data_ready()
        batch.action_compute()
        report = self.env.ref('sl_monthly_bonus.action_report_bonus_department')
        content, _ct = self.env['ir.actions.report'].sudo()._render_qweb_html(
            report.id, [batch.id],
        )
        self.assertTrue(content and len(content) > 100)

    def test_payout_xlsx_export_state_guard(self):
        batch = self._new_batch(name='RM XlsxGuard')
        with self.assertRaises(UserError):
            batch.action_export_payout_xlsx()
        batch.action_mark_data_ready()
        with self.assertRaises(UserError):
            batch.action_export_payout_xlsx()
        batch.action_compute()
        with self.assertRaises(UserError):
            batch.action_export_payout_xlsx()
        batch.action_send_to_review()
        action = batch.action_export_payout_xlsx()
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        self.assertIn('payout.xlsx', action.get('url'))
