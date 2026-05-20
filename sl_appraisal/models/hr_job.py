from odoo import fields, models, Command


class HrJob(models.Model):
    _inherit = 'hr.job'

    skill_ids = fields.Many2many(domain=[('active', '=', True)])

    def _get_removed_skill_ids_from_commands(self, commands):
        self.ensure_one()
        removed = set()
        current = set(self.skill_ids.ids)
        for command in commands:
            if command[0] == Command.SET:
                new_ids = set(command[2])
                removed |= current - new_ids
                current = new_ids
            elif command[0] == Command.UNLINK:
                removed.add(command[1])
                current.discard(command[1])
            elif command[0] == Command.CLEAR:
                removed |= current
                current = set()
            elif command[0] == Command.LINK:
                current.add(command[1])
        return removed

    def _apply_skill_removal_policy(self, skill_ids):
        skills = self.env['hr.skill'].browse(skill_ids).exists()
        for skill in skills:
            if skill._has_non_draft_appraisal_lines():
                skill.write({'active': False})
            else:
                skill.unlink()

    def write(self, vals):
        removals_by_job = {}
        if 'skill_ids' in vals:
            for job in self:
                removed = job._get_removed_skill_ids_from_commands(vals['skill_ids'])
                if removed:
                    removals_by_job[job.id] = removed
        res = super().write(vals)
        for job in self:
            removed = removals_by_job.get(job.id)
            if removed:
                job._apply_skill_removal_policy(removed)
        return res
