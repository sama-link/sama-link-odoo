from odoo import models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Named excluded_company_ids (not company_ids) so it does not collide with
    # Odoo's reserved multi-company field meaning.
    excluded_company_ids = fields.Many2many(
        'res.company',
        'project_project_res_company_rel',
        'project_project_id',
        'res_company_id',
        string='Companies (Exclude)',
        domain="[('id', '!=', company_id)]",
    )

    # When enabled, tasks in this project show a "Published Date" field on their form.
    use_published_date = fields.Boolean(string="Published Date?")

    def default_get(self, fields):
        res = super(ProjectProject, self).default_get(fields)
        res['company_id'] = self.env.company.id
        return res
