from odoo import fields, models


class AppraisalSkillHistory(models.Model):
    _name = 'appraisal.skill.history'
    _description = 'Appraisal Skill Timeline'
    _order = 'appraisal_date desc, id desc'

    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='cascade')
    appraisal_id = fields.Many2one('hr.appraisal', required=True, index=True, ondelete='cascade')
    appraisal_date = fields.Date(required=True)
    skill_type_id = fields.Many2one('hr.skill.type', required=True)
    skill_id = fields.Many2one('hr.skill', required=True)
    old_level_id = fields.Many2one('hr.skill.level')
    new_level_id = fields.Many2one('hr.skill.level', required=True)
    change_state = fields.Selection([
        ('improved', 'Improved'),
        ('same', 'Same'),
        ('declined', 'Declined'),
        ('new', 'New'),
    ], default='same', required=True)
