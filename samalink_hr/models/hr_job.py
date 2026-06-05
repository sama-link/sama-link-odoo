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

    def _get_added_skill_ids_from_commands(self, commands):
        self.ensure_one()
        added = set()
        current = set(self.skill_ids.ids)
        for command in commands:
            if command[0] == Command.SET:
                new_ids = set(command[2])
                added |= new_ids - current
                current = new_ids
            elif command[0] == Command.LINK:
                added.add(command[1])
                current.add(command[1])
            elif command[0] == Command.CLEAR:
                current = set()
            elif command[0] == Command.UNLINK:
                current.discard(command[1])
        return added

    def _add_skills_to_employees(self, added_skill_ids):
        if not added_skill_ids:
            return
        skills = self.env['hr.skill'].browse(list(added_skill_ids)).exists()
        if not skills:
            return
        employees = self.env['hr.employee'].search([('job_id', 'in', self.ids)])
        for employee in employees:
            employee._add_job_skills_to_employee(skills)

    def write(self, vals):
        removals_by_job = {}
        additions_by_job = {}
        if 'skill_ids' in vals:
            for job in self:
                removed = job._get_removed_skill_ids_from_commands(vals['skill_ids'])
                if removed:
                    removals_by_job[job.id] = removed
                added = job._get_added_skill_ids_from_commands(vals['skill_ids'])
                if added:
                    additions_by_job[job.id] = added
        res = super().write(vals)
        for job in self:
            removed = removals_by_job.get(job.id)
            if removed:
                job._remove_skills_from_employees(removed)
            added = additions_by_job.get(job.id)
            if added:
                job._add_skills_to_employees(added)
        return res
