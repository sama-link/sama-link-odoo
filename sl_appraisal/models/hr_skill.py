from odoo import fields, models, _


class HrSkill(models.Model):
    _inherit = 'hr.skill'

    active = fields.Boolean(default=True, string='Active')

    def _has_non_draft_appraisal_lines(self):
        self.ensure_one()
        if 'appraisal.skill.line' not in self.env:
            return False
        return bool(self.env['appraisal.skill.line'].search_count([
            ('skill_id', '=', self.id),
            ('state', '!=', 'draft'),
        ], limit=1))

    def unlink(self):
        to_archive = self.env['hr.skill']
        to_delete = self.env['hr.skill']
        for skill in self:
            if skill._has_non_draft_appraisal_lines():
                to_archive |= skill
            else:
                to_delete |= skill
        if to_archive:
            to_archive.write({'active': False})
        if to_delete:
            return super(HrSkill, to_delete).unlink()
        return True
