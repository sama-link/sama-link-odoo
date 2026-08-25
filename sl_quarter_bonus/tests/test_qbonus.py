from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuarterBonus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'QB Test Company'})
        cls.env.user.write({
            'company_ids': [(4, cls.company.id)],
            'groups_id': [(4, cls.env.ref('sl_quarter_bonus.group_qbonus_admin').id)],
        })
        cls.Quarter = cls.env['sl.qbonus.quarter']
        cls.Project = cls.env['sl.qbonus.project']
        cls.owner = cls.env['hr.employee'].create({'name': 'QB Owner', 'company_id': cls.company.id})
        cls.sara = cls.env['hr.employee'].create({'name': 'QB Sara', 'company_id': cls.company.id})
        cls.mona = cls.env['hr.employee'].create({'name': 'QB Mona', 'company_id': cls.company.id})
        cls.quarter = cls.Quarter._get_or_create(cls.company, date.today())
        cls.quarter.pool_amount = 120000.0

    def _project(self, name, points, kpi=100.0, **extra):
        vals = {
            'name': name,
            'company_id': self.company.id,
            'owner_id': self.owner.id,
            'date_start': date.today().replace(day=1),
            'date_end': date.today(),
            'quarter_id': self.quarter.id,
            'points_approved': points,
        }
        vals.update(extra)
        project = self.Project.create(vals)
        project.action_approve()
        project.action_start()
        project.action_submit()
        project.kpi_achievement_pct = kpi
        project.action_receive()
        return project

    def test_points_and_rate(self):
        a = self._project('ERP rollout', 120)
        b = self._project('Fiber network', 80, kpi=75.0)
        c = self._project('Helpdesk', 40, kpi=50.0)
        self.assertEqual(a.points_earned, 120)
        self.assertEqual(b.points_earned, 60)
        self.assertEqual(c.points_earned, 20)
        self.assertEqual(a.bonus_quarter_id, self.quarter)
        self.assertAlmostEqual(self.quarter.total_points, 200)
        self.assertAlmostEqual(self.quarter.rate_per_point, 600)

    def test_equal_split_with_owner_share(self):
        project = self._project('ERP rollout', 120)
        project.write({
            'owner_share_pct': 25.0,
            'member_line_ids': [
                (0, 0, {'employee_id': self.sara.id}),
                (0, 0, {'employee_id': self.mona.id}),
            ],
        })
        project.action_distribute()
        by_emp = {l.employee_id: l for l in project.member_line_ids}
        self.assertEqual(by_emp[self.owner].role, 'owner')
        self.assertAlmostEqual(by_emp[self.owner].points, 30)
        self.assertAlmostEqual(by_emp[self.sara].points, 45)
        self.assertAlmostEqual(by_emp[self.mona].points, 45)
        self.assertAlmostEqual(project.points_undistributed, 0)
        self.assertAlmostEqual(by_emp[self.sara].amount, 45 * self.quarter.rate_per_point)

    def test_ratio_split(self):
        project = self._project('Fiber network', 80, kpi=75.0, split_method='ratio', owner_share_pct=20.0)
        project.write({'member_line_ids': [
            (0, 0, {'employee_id': self.sara.id, 'ratio_pct': 50}),
            (0, 0, {'employee_id': self.mona.id, 'ratio_pct': 50}),
        ]})
        project.action_distribute()
        by_emp = {l.employee_id: l.points for l in project.member_line_ids}
        self.assertAlmostEqual(by_emp[self.owner], 12)
        self.assertAlmostEqual(by_emp[self.sara], 24)
        self.assertAlmostEqual(by_emp[self.mona], 24)

    def test_over_distribution_blocked(self):
        project = self._project('Helpdesk', 40, kpi=50.0)
        with self.assertRaises(ValidationError):
            project.write({'member_line_ids': [(0, 0, {'employee_id': self.sara.id, 'points': 25})]})

    def test_quarter_lines(self):
        project = self._project('ERP rollout', 120)
        project.write({'member_line_ids': [(0, 0, {'employee_id': self.sara.id})]})
        project.action_distribute()
        self.quarter.action_compute()
        lines = {l.employee_id: l for l in self.quarter.line_ids}
        self.assertIn(self.sara, lines)
        self.assertAlmostEqual(lines[self.sara].points + lines[self.owner].points, 120)
        self.assertAlmostEqual(sum(self.quarter.line_ids.mapped('amount')), 120000)
