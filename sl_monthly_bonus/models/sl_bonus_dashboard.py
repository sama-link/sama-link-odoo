"""Read-only aggregated view backing the dashboard menus.

Built on top of sl.bonus.batch.line via a SQL view. Gives graph & pivot
visualizations of bonus amounts by month, category, department, and employee
without exposing line-level edit affordances.
"""
from odoo import models, fields, tools


class SlBonusDashboardLine(models.Model):
    _name = 'sl.bonus.dashboard.line'
    _description = 'Bonus Dashboard Line (read-only aggregation)'
    _auto = False
    _order = 'period_start desc'

    # Identity / time
    line_id = fields.Many2one('sl.bonus.batch.line', string='Line', readonly=True)
    batch_id = fields.Many2one('sl.bonus.batch', string='Batch', readonly=True)
    batch_state = fields.Selection([
        ('draft', 'Draft'),
        ('data_ready', 'Data Ready'),
        ('computed', 'Computed'),
        ('hr_review', 'HR Review'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], string='Batch State', readonly=True)
    period_start = fields.Date(string='Month', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)

    # Subject
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', readonly=True)
    work_location_id = fields.Many2one('hr.work.location', string='Branch', readonly=True)

    # Bonus
    category = fields.Selection([
        ('service', 'Service'),
        ('sales', 'Sales'),
        ('stock', 'Stock Purchasing'),
        ('installation', 'Installation'),
        ('branch_manager', 'Branch / Area Manager'),
        ('none', 'No Monthly Bonus'),
    ], string='Category', readonly=True)
    evaluation_percent = fields.Float(string='Evaluation %', readonly=True)
    achievement_percent = fields.Float(string='Sales Achievement %', readonly=True)
    computed_amount = fields.Float(string='Computed', readonly=True)
    bonus_amount = fields.Float(string='Bonus', readonly=True)
    is_excluded = fields.Boolean(string='Excluded', readonly=True)
    has_override = fields.Boolean(string='Manually Adjusted', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    l.id                    AS id,
                    l.id                    AS line_id,
                    l.batch_id              AS batch_id,
                    b.state                 AS batch_state,
                    b.period_start          AS period_start,
                    b.company_id            AS company_id,
                    l.employee_id           AS employee_id,
                    l.department_id         AS department_id,
                    l.job_id                AS job_id,
                    l.work_location_id      AS work_location_id,
                    l.category              AS category,
                    l.evaluation_percent    AS evaluation_percent,
                    l.achievement_percent   AS achievement_percent,
                    l.computed_amount       AS computed_amount,
                    l.bonus_amount          AS bonus_amount,
                    l.is_excluded           AS is_excluded,
                    CASE WHEN l.manual_override_reason IS NOT NULL AND l.manual_override_reason <> ''
                         THEN TRUE ELSE FALSE END AS has_override,
                    b.currency_id           AS currency_id
                FROM sl_bonus_batch_line l
                JOIN sl_bonus_batch b ON b.id = l.batch_id
            )
        """)
