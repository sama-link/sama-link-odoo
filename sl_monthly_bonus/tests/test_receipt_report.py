"""Tests for the Employee Bonus Receipt PDF.

Covers:
- Render of the QWeb template for an approved line of each category.
- Access control: action_print_receipt refuses to act on draft/computed lines.
- Multi-line render produces one document.
"""
from datetime import date
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install', 'sl_monthly_bonus')
class TestBonusReceiptReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_ref = 'sl_monthly_bonus.action_report_sl_bonus_receipt'

    def _approved_line(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employee.")
        line = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id,
            'period_start': date(2030, 8, 1),
        })
        line.action_compute()
        line.action_approve()
        return line

    def test_action_blocks_draft(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employee.")
        line = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id, 'period_start': date(2030, 9, 1),
        })
        # draft → must refuse.
        with self.assertRaises(UserError):
            line.action_print_receipt()

    def test_action_blocks_computed(self):
        emp = self.env['hr.employee'].search([('active', '=', True)], limit=1)
        if not emp:
            self.skipTest("No active employee.")
        line = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id, 'period_start': date(2030, 9, 1),
        })
        line.action_compute()
        with self.assertRaises(UserError):
            line.action_print_receipt()

    def test_renders_approved_line(self):
        line = self._approved_line()
        report = self.env.ref(self.report_ref)
        # _render_qweb_pdf returns (content_bytes, format_str).
        # We don't invoke a full PDF render (wkhtmltopdf may not be present in
        # test mode); instead render the HTML which exercises the template.
        html, _fmt = report._render_qweb_html(self.report_ref, line.ids)
        self.assertIn(b'\xd9\x85\xd9\x83\xd8\xa7\xd9\x81\xd8\xa3\xd8\xa9', html)  # 'مكافأة'
        self.assertIn(line.employee_id.name.encode('utf-8'), html)

    def test_renders_multi_lines(self):
        line1 = self._approved_line()
        # Make a second one for a different month.
        emp = self.env['hr.employee'].search([
            ('active', '=', True), ('id', '!=', line1.employee_id.id),
        ], limit=1)
        if not emp:
            self.skipTest("Need at least 2 active employees.")
        line2 = self.env['sl.bonus.batch.line'].create({
            'employee_id': emp.id, 'period_start': date(2030, 8, 1),
        })
        line2.action_compute()
        line2.action_approve()
        report = self.env.ref(self.report_ref)
        html, _fmt = report._render_qweb_html(
            self.report_ref, (line1 + line2).ids,
        )
        self.assertIn(line1.employee_id.name.encode('utf-8'), html)
        self.assertIn(line2.employee_id.name.encode('utf-8'), html)
