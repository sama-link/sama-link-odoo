"""Tests for the 18.0.2.1.0 refinement batch.

Covers:
- Add Employees wizard (specific / all / by_department modes).
- Add From Appraisal Batch wizard (uses an hr.appraisal.batch's appraisals).
- Duplicate prevention across both wizards.
- My Bonus menu label has no emoji prefix.
- Receipt template renders for an approved line and includes the new
  Cairo-friendly font reference and the evaluation indicator emoji.
- Localized month display (period_display field) returns a human-readable
  string in the active language.
"""
from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestRefinements(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Far-future period to avoid clashes with real DB batches.
        cls.period_start = date(2031, 1, 1)
        cls.period_end = date(2031, 1, 31)

    def _new_batch(self, name='Test Refinement Batch'):
        return self.env['sl.bonus.batch'].create({
            'name': name,
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    # ─── Add Employees wizard ─────────────────────────────────────────
    def test_add_employees_wizard_specific(self):
        batch = self._new_batch('Specific Wizard Batch')
        emps = self.env['hr.employee'].search([('active', '=', True)], limit=3)
        if len(emps) < 2:
            self.skipTest("Need at least 2 active employees.")
        wizard = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id,
            'mode': 'specific',
            'employee_ids': [(6, 0, emps.ids)],
        })
        self.assertEqual(wizard.preview_count, len(emps))
        wizard.action_confirm()
        self.assertEqual(
            set(batch.line_ids.mapped('employee_id.id')),
            set(emps.ids),
        )

    def test_add_employees_wizard_all(self):
        batch = self._new_batch('All Wizard Batch')
        wizard = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id,
            'mode': 'all',
        })
        # preview_count should reflect every active employee in this company
        # that isn't already in the batch.
        all_active = self.env['hr.employee'].sudo().search([
            ('company_id', 'in', [batch.company_id.id, False]),
            ('active', '=', True),
        ])
        if not all_active:
            self.skipTest("No active employees.")
        self.assertEqual(wizard.preview_count, len(all_active))
        wizard.action_confirm()
        self.assertEqual(len(batch.line_ids), len(all_active))

    def test_add_employees_wizard_by_department(self):
        batch = self._new_batch('Dept Wizard Batch')
        # Pick a department that has active employees in the batch's company —
        # the wizard's _candidate_employees applies the same company filter.
        dept = self.env['hr.department'].search([], limit=1)
        if not dept:
            self.skipTest("No departments in DB.")
        company_domain = [
            ('department_id', '=', dept.id),
            ('active', '=', True),
            ('company_id', 'in', [batch.company_id.id, False]),
        ]
        dept_emps = self.env['hr.employee'].sudo().search(company_domain)
        if not dept_emps:
            self.skipTest("Picked department has no active employees in batch company.")
        wizard = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id,
            'mode': 'by_department',
            'department_ids': [(6, 0, [dept.id])],
        })
        self.assertEqual(wizard.preview_count, len(dept_emps))
        wizard.action_confirm()
        self.assertEqual(
            set(batch.line_ids.mapped('employee_id.id')),
            set(dept_emps.ids),
        )

    def test_add_employees_wizard_skips_duplicates(self):
        batch = self._new_batch('Dup Wizard Batch')
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employees.")
        # Seed the batch with the employee directly.
        batch.line_ids = [(0, 0, {'employee_id': emp.id})]
        before = len(batch.line_ids)
        wizard = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id,
            'mode': 'specific',
            'employee_ids': [(6, 0, [emp.id])],
        })
        # preview_count should report 0 — already present.
        self.assertEqual(wizard.preview_count, 0)
        # Confirming with nothing to add should raise (better UX than silent).
        # In our impl: empty candidates raises; pre-filtered duplicates path
        # is handled gracefully — both surfaces are valid.
        # Here, candidates == [emp] but all are duplicates → 0 new lines created.
        # The wizard's UI hides the button when preview_count<=0; calling
        # action_confirm directly still works and yields 0 created.
        notif = wizard.action_confirm()
        self.assertEqual(len(batch.line_ids), before)
        self.assertEqual(notif['tag'], 'display_notification')

    def test_add_employees_wizard_blocked_after_approval(self):
        batch = self._new_batch('Approve Wizard Batch')
        batch.action_mark_data_ready()
        batch.action_compute()
        if not batch.line_ids:
            self.skipTest("No active employees.")
        batch.action_approve()
        wizard = self.env['sl.bonus.add.employees.wizard'].create({
            'batch_id': batch.id,
            'mode': 'all',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # ─── Add From Appraisal Batch wizard ──────────────────────────────
    def test_add_from_appraisal_wizard(self):
        # Build a tiny appraisal batch with one appraisal referencing an
        # existing employee — appraisal state is irrelevant per the brief.
        emp = self.env['hr.employee'].search([
            ('active', '=', True), ('user_id', '!=', False),
        ], limit=1)
        if not emp:
            emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        appraisal_batch = self.env['hr.appraisal.batch'].create({
            'name': 'Test Appraisal Batch 2031',
            'date_from': self.period_start,
            'date_to': self.period_end,
            'date_deadline': date(2031, 2, 28),
        })
        self.env['hr.appraisal'].create({
            'employee_id': emp.id,
            'appraisal_batch_id': appraisal_batch.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': date(2031, 2, 28),
        })
        bonus_batch = self._new_batch('From Appraisal Wizard Batch')
        wizard = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id,
            'appraisal_batch_id': appraisal_batch.id,
        })
        self.assertEqual(wizard.candidate_count, 1)
        self.assertEqual(wizard.preview_count, 1)
        wizard.action_confirm()
        self.assertEqual(
            set(bonus_batch.line_ids.mapped('employee_id.id')),
            {emp.id},
        )

    def test_add_from_appraisal_wizard_skips_duplicates(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        appraisal_batch = self.env['hr.appraisal.batch'].create({
            'name': 'Dup Appraisal Batch 2031',
            'date_from': self.period_start,
            'date_to': self.period_end,
            'date_deadline': date(2031, 2, 28),
        })
        self.env['hr.appraisal'].create({
            'employee_id': emp.id,
            'appraisal_batch_id': appraisal_batch.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': date(2031, 2, 28),
        })
        bonus_batch = self._new_batch('Dup From Appraisal Batch')
        bonus_batch.line_ids = [(0, 0, {'employee_id': emp.id})]
        wizard = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id,
            'appraisal_batch_id': appraisal_batch.id,
        })
        self.assertEqual(wizard.preview_count, 0)

    def test_add_from_appraisal_does_not_modify_appraisal(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No employees.")
        appraisal_batch = self.env['hr.appraisal.batch'].create({
            'name': 'Read-Only Appraisal Batch 2031',
            'date_from': self.period_start,
            'date_to': self.period_end,
            'date_deadline': date(2031, 2, 28),
        })
        appraisal = self.env['hr.appraisal'].create({
            'employee_id': emp.id,
            'appraisal_batch_id': appraisal_batch.id,
            'date_from': self.period_start,
            'date_to': self.period_end,
            'appraisal_deadline': date(2031, 2, 28),
        })
        original_state = appraisal.state
        original_emp = appraisal.employee_id
        bonus_batch = self._new_batch('No-Modify Appraisal Batch')
        wizard = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': bonus_batch.id,
            'appraisal_batch_id': appraisal_batch.id,
        })
        wizard.action_confirm()
        appraisal.invalidate_recordset()
        self.assertEqual(appraisal.state, original_state,
                         "Appraisal state must not change.")
        self.assertEqual(appraisal.employee_id, original_emp,
                         "Appraisal employee must not change.")

    # ─── My Bonus menu label ──────────────────────────────────────────
    def test_my_bonus_menu_has_no_emoji(self):
        menu = self.env.ref('sl_monthly_bonus.menu_sl_bonus_self')
        # The 'name' field is translated; we check the English source string
        # via the JSONB column directly (so we test the source, not whichever
        # translation happens to be active).
        self.env.cr.execute(
            "SELECT name FROM ir_ui_menu WHERE id = %s", (menu.id,)
        )
        name_jsonb = self.env.cr.fetchone()[0]
        # name is jsonb like {"en_US": "My Bonus", "ar_001": "مكافأتي"}.
        for lang, label in (name_jsonb or {}).items():
            self.assertNotIn('👤', label,
                             "Emoji must NOT appear in My Bonus menu label "
                             "(found in %s='%s')." % (lang, label))

    # ─── Localized month display ──────────────────────────────────────
    def test_period_display_is_human_readable(self):
        batch = self._new_batch('Period Display Batch')
        # English context — value should be readable (no '2031-01' format).
        en = batch.with_context(lang='en_US').period_display
        self.assertTrue(en, "period_display must be non-empty.")
        # The raw label format is YYYY-MM. The display must not equal it
        # exactly (it should be a month name + year, e.g. "January 2031").
        self.assertNotEqual(en, batch.period_label,
                            "period_display must differ from the YYYY-MM label.")
        # Arabic context — should also be non-empty (locale may yield the
        # Arabic month name or fall back to a babel-supported variant).
        ar = batch.with_context(lang='ar_001').period_display
        self.assertTrue(ar, "period_display in Arabic must be non-empty.")

    # ─── Receipt rendering with the new design ────────────────────────
    def test_receipt_renders_with_cairo_and_indicator(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employees.")
        line = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id,
            'period_start': self.period_start,
        })
        line.action_compute()
        line.action_approve()
        report = self.env.ref('sl_monthly_bonus.action_report_sl_bonus_receipt')
        html, _fmt = report._render_qweb_html(
            'sl_monthly_bonus.action_report_sl_bonus_receipt', line.ids,
        )
        # Cairo font import marker present in the rendered HTML.
        self.assertIn(b'Cairo', html,
                      "Receipt must reference Cairo font family.")
        # The evaluation block exists.
        self.assertIn(b'\xd8\xaa\xd9\x82\xd9\x8a\xd9\x8a\xd9\x85', html)  # 'تقييم'
        # The polished final amount section is present.
        self.assertIn(b'sl-final', html)
