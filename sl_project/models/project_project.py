from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Multi-select companies for the project; shown instead of core company_id.
    company_ids = fields.Many2many(
        'res.company',
        'sl_project_project_company_rel',
        'project_id',
        'company_id',
        string='Company',
        default=lambda self: self.env.company,
    )

    # When enabled, tasks in this project show a "Published Date" field on their form.
    use_published_date = fields.Boolean(string="Published Date?")

    def init(self):
        """Backfill company_ids from legacy single company_id on upgrade."""
        super().init()
        self.env.cr.execute("""
            INSERT INTO sl_project_project_company_rel (project_id, company_id)
            SELECT p.id, p.company_id
              FROM project_project p
             WHERE p.company_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM sl_project_project_company_rel r
                     WHERE r.project_id = p.id
                       AND r.company_id = p.company_id
               )
        """)

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        company = self.env.company
        if 'company_id' in fields_list or not fields_list:
            res['company_id'] = company.id
        if 'company_ids' in fields_list or not fields_list:
            res['company_ids'] = [(6, 0, [company.id])]
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'company_ids' in vals and 'company_id' not in vals:
                vals['company_id'] = self._primary_company_id_from_commands(vals['company_ids'])
            elif vals.get('company_id') and 'company_ids' not in vals:
                vals['company_ids'] = [(6, 0, [vals['company_id']])]
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        sync_primary_from_m2m = 'company_ids' in vals and 'company_id' not in vals
        if vals.get('company_id') and 'company_ids' not in vals:
            vals['company_ids'] = [(4, vals['company_id'])]
        elif 'company_id' in vals and not vals['company_id'] and 'company_ids' not in vals:
            vals['company_ids'] = [(5, 0, 0)]
        res = super().write(vals)
        if sync_primary_from_m2m:
            for project in self:
                primary = project.company_ids[:1]
                if project.company_id != primary:
                    super(ProjectProject, project).write({
                        'company_id': primary.id if primary else False,
                    })
        return res

    @api.model
    def _primary_company_id_from_commands(self, commands):
        """Resolve primary company_id from a full company_ids command list."""
        ids = []
        for command in commands or []:
            if not command:
                continue
            op = command[0]
            if op == 6:
                ids = list(command[2] or [])
            elif op == 5:
                ids = []
            elif op == 4 and command[1]:
                if command[1] not in ids:
                    ids.append(command[1])
            elif op == 3 and command[1] in ids:
                ids.remove(command[1])
        return ids[0] if ids else False

    @api.onchange('company_ids')
    def _onchange_company_ids(self):
        self.company_id = self.company_ids[:1]

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id and self.company_id not in self.company_ids:
            self.company_ids = self.company_ids | self.company_id
