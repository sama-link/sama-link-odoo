from odoo import models, fields

class HrJob(models.Model):
    _inherit = 'hr.job'

    skill_ids = fields.Many2many('hr.skill', string='Skills Required')