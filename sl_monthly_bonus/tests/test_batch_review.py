"""Bonus batch review wizard: employees whose contract starts or ends inside
the bonus period are hidden from the Add Employees wizard and decided one
by one in ``sl.bonus.batch.review``.

Covers:
  * contract starting / ending inside the period is flagged; a contract
    covering the whole period, or ending before it, is not
  * flagged employees are excluded from every Add Employees mode
  * action_confirm with a flagged specific employee opens the review wizard
    and carries the unflagged ones
  * review confirm adds the included, skips the excluded, notes it in chatter
  * Add From Appraisal Batch routes flagged employees the same way
"""
from datetime import date

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'sl_monthly_bonus', 'sl_monthly_bonus_review')
class TestBatchReview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Far-future period so no real DB rows clash.
        cls.period_start = date(2034, 5, 1)
        cls.period_end = date(2034, 5, 31)
        cls.dept = cls.env['hr.department'].create({'name': 'Review Dept 2034'})

    def _employee(self, name, date_start, date_end=None, job=None):
        emp = self.env['hr.employee'].create({'name': name, 'department_id': self.dept.id})
        self.env['hr.contract'].create({
            'name': f'C {name}', 'employee_id': emp.id, 'wage': 9000.0,
            'state': 'open', 'date_start': date_start, 'date_end': date_end,
        })
        return emp

    def _batch(self, name='Review Batch 2034-05'):
        return self.env['sl.bonus.batch'].create({
            'name': name,
            'period_start': self.period_start,
            'period_end': self.period_end,
        })

    def _wizard(self, batch, **vals):
        return self.env['sl.bonus.add.employees.wizard'].create({'batch_id': batch.id, **vals})

    # ── detection ────────────────────────────────────────────────────
    def test_detection(self):
        full = self._employee('Full Period', date(2030, 1, 1))
        hired = self._employee('Hired Mid', date(2034, 5, 10))
        left = self._employee('Left Mid', date(2030, 1, 1), date(2034, 5, 20))
        gone = self._employee('Gone Before', date(2030, 1, 1), date(2034, 4, 30))
        batch = self._batch()
        issues = batch._employee_period_issues(full | hired | left | gone)
        self.assertNotIn(full.id, issues)
        self.assertIn(hired.id, issues)
        self.assertIn('starts 2034-05-10', issues[hired.id]['summary'])
        self.assertIn(left.id, issues)
        self.assertIn('ends 2034-05-20', issues[left.id]['summary'])
        # no contract overlapping the period is NOT a bonus problem
        self.assertNotIn(gone.id, issues)

    # ── add-employees wizard hides flagged employees ─────────────────
    def test_wizard_hides_flagged_in_every_mode(self):
        full = self._employee('Full A', date(2030, 1, 1))
        hired = self._employee('Hired A', date(2034, 5, 3))
        batch = self._batch('Hide Batch')
        wiz = self._wizard(batch, mode='by_department', department_ids=[(6, 0, self.dept.ids)])
        self.assertIn(hired, wiz.issue_employee_ids)
        self.assertEqual(wiz.issue_count, len(wiz.issue_employee_ids))
        candidates = wiz._candidate_employees()
        self.assertIn(full, candidates)
        self.assertNotIn(hired, candidates)
        wiz.mode = 'all'
        self.assertNotIn(hired, wiz._candidate_employees())
        wiz.mode = 'specific'
        wiz.employee_ids = [(6, 0, (full | hired).ids)]
        self.assertEqual(wiz._candidate_employees(), full)

    def test_confirm_routes_flagged_to_review(self):
        full = self._employee('Full B', date(2030, 1, 1))
        hired = self._employee('Hired B', date(2034, 5, 3))
        batch = self._batch('Route Batch')
        # the wizard's own candidate filter would drop `hired`; go through
        # the batch entry point the way the review wizard does
        action = batch._open_review_wizard(hired, full)
        self.assertEqual(action['res_model'], 'sl.bonus.batch.review')
        review = self.env['sl.bonus.batch.review'].browse(action['res_id'])
        self.assertEqual(review.ok_employee_ids, full)
        self.assertEqual(review.line_ids.mapped('employee_id'), hired)
        self.assertEqual(review.line_ids.decision, 'include')

        review.line_ids.decision = 'exclude'
        review.action_confirm()
        self.assertEqual(batch.line_ids.mapped('employee_id'), full)
        bodies = " ".join(batch.message_ids.mapped('body'))
        self.assertIn('Skipped 1 employee', bodies)
        self.assertIn('Hired B', bodies)

    def test_review_include_adds_line(self):
        hired = self._employee('Hired C', date(2034, 5, 3))
        batch = self._batch('Include Batch')
        action = batch._open_review_wizard(hired)
        review = self.env['sl.bonus.batch.review'].browse(action['res_id'])
        review.action_confirm()
        self.assertEqual(batch.line_ids.mapped('employee_id'), hired)

    # ── add-from-appraisal wizard ────────────────────────────────────
    def test_add_from_appraisal_routes_flagged(self):
        full = self._employee('Full D', date(2030, 1, 1))
        left = self._employee('Left D', date(2030, 1, 1), date(2034, 5, 15))
        appraisal_batch = self.env['hr.appraisal.batch'].create({
            'name': 'Appraisal 2034-05', 'date_from': self.period_start,
            'date_to': self.period_end, 'date_deadline': date(2034, 6, 30),
        })
        appraisal_batch._generate_appraisals_for_employees(full)
        # `left` has a contract boundary in the appraisal period too — add it
        # through the appraisal review path so the bonus side sees it.
        appraisal_batch._generate_appraisals_for_employees(left)
        batch = self._batch('From Appraisal Batch')
        wiz = self.env['sl.bonus.add.from.appraisal.wizard'].create({
            'batch_id': batch.id, 'appraisal_batch_id': appraisal_batch.id,
        })
        action = wiz.action_confirm()
        self.assertEqual(action.get('res_model'), 'sl.bonus.batch.review')
        self.assertEqual(batch.appraisal_batch_id, appraisal_batch)
        review = self.env['sl.bonus.batch.review'].browse(action['res_id'])
        self.assertEqual(review.ok_employee_ids, full)
        self.assertEqual(review.line_ids.mapped('employee_id'), left)
