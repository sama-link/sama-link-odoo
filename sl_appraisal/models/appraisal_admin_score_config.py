from odoo import api, fields, models


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
    active = fields.Boolean(default=True)

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
