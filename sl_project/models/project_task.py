from odoo import models, fields, api

class ProjectTask(models.Model):
    _inherit = 'project.task'

    company_ids = fields.Many2many(
        'res.company',
        string='Companies (Exclude)',
        domain="[('id', '!=', company_id)]",
        compute='_compute_company_ids', store=True,
        readonly=False, recursive=True, copy=True,
    )

    @api.depends('project_id.company_ids', 'parent_id.company_ids')
    def _compute_company_ids(self):
        for task in self:
            if not task.parent_id and not task.project_id:
                continue
            task.company_ids = task.project_id.company_ids or task.parent_id.company_ids