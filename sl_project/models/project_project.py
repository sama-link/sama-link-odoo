from odoo import models, fields

class ProjectProject(models.Model):
    _inherit = 'project.project'

    company_ids = fields.Many2many(
        'res.company',
        string='Companies (Exclude)',
        domain="[('id', '!=', company_id)]",
    )

    def default_get(self, fields):
        res = super(ProjectProject, self).default_get(fields)
        res['company_id'] = self.env.company.id
        return res