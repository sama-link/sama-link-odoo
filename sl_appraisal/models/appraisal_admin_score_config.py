from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AppraisalAdminScoreConfig(models.Model):
    _name = 'appraisal.admin.score.config'
    _description = 'Appraisal Administration Score Configuration'

    name = fields.Char(default='Default Administration Scoring', required=True)
    absence_points = fields.Float(
        string='Points Per Unexcused Absence Day',
        default=-10.0,
        required=True,
    )
    late_points = fields.Float(
        string='Points Per Late Day',
        default=-5.0,
        required=True,
    )
    early_leaving_points = fields.Float(
        string='Points Per Early Leaving Day',
        default=-5.0,
        required=True,
    )
    penalty_points = fields.Float(
        string='Points Per Penalty',
        default=-15.0,
        required=True,
    )
    bonus_points = fields.Float(
        string='Points Per Bonus',
        default=15.0,
        required=True,
    )
    manual_score_limit = fields.Float(
        string='Manual Adjustment Limit (±)',
        default=15.0,
        required=True,
        help="Maximum positive or negative manual adjustment after the base score. "
             "Set to 0 to disable manual adjustments.",
    )
    active = fields.Boolean(default=True)

    @api.constrains('manual_score_limit')
    def _check_manual_score_limit(self):
        for config in self:
            if config.manual_score_limit < 0:
                raise ValidationError(
                    _("Manual adjustment limit cannot be negative.")
                )

    @api.model
    def get_config(self):
        config = self.search([('active', '=', True)], limit=1, order='id asc')
        if not config:
            config = self.create({})
        return config

    @api.model
    def action_open_config(self):
        config = self.get_config()
        return {
            'name': 'Administration Score Configuration',
            'type': 'ir.actions.act_window',
            'res_model': 'appraisal.admin.score.config',
            'view_mode': 'form',
            'res_id': config.id,
            'target': 'current',
        }
