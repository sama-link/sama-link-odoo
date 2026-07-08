from odoo import api, fields, models


class SlFreelancerProjectLine(models.Model):
    _name = 'sl.freelancer.project.line'
    _description = 'Freelancer Project/Task Line'
    _check_company_auto = True

    freelancer_task_id = fields.Many2one(
        'sl.freelancer.task', string='Freelancer Record',
        required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one(
        related='freelancer_task_id.employee_id', string='Employee', store=True)
    company_id = fields.Many2one(
        related='freelancer_task_id.company_id', string='Company', store=True)
    project_id = fields.Many2one(
        'project.project', string='Project', required=True)
    task_id = fields.Many2one(
        'project.task', string='Task', required=True,
        domain="[('project_id', '=', project_id)]")

    @api.onchange('project_id')
    def _onchange_project_id(self):
        """Reset the task when it no longer belongs to the chosen project."""
        if self.task_id.project_id != self.project_id:
            self.task_id = False
