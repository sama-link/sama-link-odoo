from odoo import api, fields, models
from odoo.tools import float_compare


class SlQbonusLine(models.Model):
    """Per-employee result of a quarter, built by ``sl.qbonus.quarter.action_compute``.

    Plain stored values (not computes) so the dashboard can pivot and graph
    them, and so a closed quarter keeps the figures it was closed with.
    """
    _name = 'sl.qbonus.line'
    _description = 'Quarterly Bonus Employee Line'
    _order = 'quarter_id desc, amount desc'
    _rec_name = 'employee_id'

    quarter_id = fields.Many2one(
        'sl.qbonus.quarter', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='quarter_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    quarter_state = fields.Selection(related='quarter_id.state', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, index=True)
    user_id = fields.Many2one(related='employee_id.user_id', store=True, index=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    job_id = fields.Many2one(related='employee_id.job_id', store=True)
    project_ids = fields.Many2many(
        'sl.qbonus.project', 'sl_qbonus_line_project_rel', 'line_id', 'project_id',
        string='Projects')
    project_count = fields.Integer(compute='_compute_project_count', store=True)
    points = fields.Float(digits=(16, 2))
    amount = fields.Monetary(string='Quarter Bonus', currency_field='currency_id')
    basic_salary = fields.Monetary(currency_field='currency_id')
    project_months = fields.Float(digits=(16, 2))
    monthly_equivalent = fields.Monetary(
        string='Monthly Method (project months)', currency_field='currency_id',
        help='baseline % x basic salary x sum of project months')
    calendar_equivalent = fields.Monetary(
        string='Monthly Method (3 months)', currency_field='currency_id',
        help='baseline % x basic salary x 3 calendar months')
    diff = fields.Monetary(
        string='Difference', compute='_compute_comparison', store=True,
        currency_field='currency_id')
    diff_pct = fields.Float(string='Difference %', compute='_compute_comparison', store=True, digits=(16, 1))
    beats_monthly = fields.Boolean(compute='_compute_comparison', store=True)
    beats_calendar = fields.Boolean(compute='_compute_comparison', store=True)
    trend = fields.Char(compute='_compute_trend')

    @api.depends('project_ids')
    def _compute_project_count(self):
        for line in self:
            line.project_count = len(line.project_ids)

    @api.depends('amount', 'monthly_equivalent', 'calendar_equivalent')
    def _compute_comparison(self):
        for line in self:
            line.diff = line.amount - line.monthly_equivalent
            line.diff_pct = (line.diff / line.monthly_equivalent * 100.0) if line.monthly_equivalent else 0.0
            line.beats_monthly = float_compare(line.diff, 0.0, precision_digits=2) >= 0
            line.beats_calendar = float_compare(line.amount, line.calendar_equivalent, precision_digits=2) >= 0

    def _compute_trend(self):
        for line in self:
            line.trend = '▲' if line.beats_monthly else '▼'
