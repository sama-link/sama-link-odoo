from odoo import models, fields

class ProjectProject(models.Model):
    _inherit = 'project.project'

    company_ids = fields.Many2many(
        'res.company',
        string='Companies (Exclude)',
        domain="[('id', '!=', company_id)]",
    )

    # When enabled, tasks in this project show a "Published Date" field on their form.
    use_published_date = fields.Boolean(string="Published Date?")

    def default_get(self, fields):
        res = super(ProjectProject, self).default_get(fields)
        res['company_id'] = self.env.company.id
        return res