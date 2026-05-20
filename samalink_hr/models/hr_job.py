from odoo import models, fields, Command


class HrJob(models.Model):
    _inherit = 'hr.job'

    skill_ids = fields.Many2many('hr.skill', string='Skills Required')

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

    def _remove_skills_from_employees(self, removed_skill_ids):
        if not removed_skill_ids:
            return
        employees = self.env['hr.employee'].search([('job_id', 'in', self.ids)])
        if not employees:
            return
        employee_skills = self.env['hr.employee.skill'].search([
            ('employee_id', 'in', employees.ids),
            ('skill_id', 'in', list(removed_skill_ids)),
        ])
        if employee_skills:
            employee_skills.unlink()

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
                job._remove_skills_from_employees(removed)
        return res
