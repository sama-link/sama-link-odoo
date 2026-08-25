from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    qbonus_baseline_pct = fields.Float(
        string='Monthly Baseline %', default=25.0,
        config_parameter='sl_quarter_bonus.baseline_pct',
        help='Used to compare the quarter bonus with the monthly method: '
             'baseline % x basic salary x project months. New quarters copy this value.')
    qbonus_late_penalty_pct = fields.Float(
        string='Default Late Penalty %', default=10.0,
        config_parameter='sl_quarter_bonus.late_penalty_pct',
        help='Suggested penalty, as a % of the approved points, when a project '
             'is submitted after the end of its target quarter. The admin can '
             'change the penalty before receiving the project.')
