from odoo import api, fields, models

APPRAISAL_ADMIN_SCORE_MODES = [
    ('scored', 'Has administrative score'),
    ('exempt', 'No administrative score (always 100%)'),
]


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    appraisal_ids = fields.One2many(
        'hr.appraisal', 'employee_id',
        string='Appraisals',
        help="All appraisals for this employee")

    appraisal_count = fields.Integer(
        string='Appraisal Count',
        compute='_compute_appraisal_count')

    last_appraisal_date = fields.Date(
        string='Last Appraisal',
        compute='_compute_last_appraisal_date',
        help="Date of the most recent finalized appraisal")

    appraisal_skill_history_ids = fields.One2many(
        'appraisal.skill.history',
        'employee_id',
        string='Skill Timeline',
        help="Timeline of skill changes approved from appraisals.")

    # ── Appraisal eligibility (employee card → "Appraisal & Bonus" tab) ──
    appraisal_eligible = fields.Boolean(
        string='Appraisal',
        default=True,
        help="Uncheck to exclude this employee from appraisals: they can no "
             "longer be selected when creating appraisals or appraisal batches.",
    )
    appraisal_admin_score_mode = fields.Selection(
        APPRAISAL_ADMIN_SCORE_MODES,
        string='Administrative Score',
        default='scored',
        help="'No administrative score' puts the employee on the Administrative "
             "Exclude list (Appraisals → Configuration): their administration "
             "score is always 100%, regardless of absences, lateness or "
             "penalties. The two stay in sync both ways.",
    )

    def _has_active_contract_in_period(self, date_from, date_to):
        """True when the employee holds a running or closed contract that
        overlaps [date_from, date_to] — i.e. the employee was actually
        employed during (part of) the appraisal period. Draft/cancelled
        contracts don't count."""
        self.ensure_one()
        if not date_from or not date_to:
            return True
        # active_test=False: archiving an employee archives their contracts
        # too — a departed employee who worked during the period still counts.
        return bool(self.env['hr.contract'].sudo().with_context(
            active_test=False,
        ).search_count([
            ('employee_id', '=', self.id),
            ('state', 'in', ('open', 'close')),
            ('date_start', '<=', date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', date_from),
        ]))

    @api.depends('appraisal_ids')
    def _compute_appraisal_count(self):
        appraisal_data = self.env['hr.appraisal'].sudo().read_group(
            domain=[('employee_id', 'in', self.ids)],
            fields=['employee_id'],
            groupby=['employee_id'],
        )
        mapped_data = {
            item['employee_id'][0]: item['employee_id_count']
            for item in appraisal_data
        }
        for employee in self:
            employee.appraisal_count = mapped_data.get(employee.id, 0)

    @api.depends('appraisal_ids', 'appraisal_ids.state')
    def _compute_last_appraisal_date(self):
        for employee in self:
            finalized = employee.appraisal_ids.filtered(
                lambda a: a.state == 'hr_finalization'
            ).sorted('date_to', reverse=True)
            employee.last_appraisal_date = (
                finalized[0].date_to if finalized else False)

    # ── Appraisal eligibility ⇄ Administrative Exclude list sync ──────
    @api.onchange('appraisal_eligible')
    def _onchange_appraisal_eligible(self):
        if not self.appraisal_eligible:
            self.appraisal_admin_score_mode = 'scored'

    @api.model
    def _normalize_appraisal_eligibility_vals(self, vals):
        """An employee who cannot take appraisals has no administrative-score
        setting either: reset it so re-enabling starts from the default."""
        if 'appraisal_eligible' in vals and not vals['appraisal_eligible']:
            vals['appraisal_admin_score_mode'] = 'scored'
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_appraisal_eligibility_vals(vals)
        employees = super().create(vals_list)
        employees._sync_admin_score_exclude()
        return employees

    def write(self, vals):
        self._normalize_appraisal_eligibility_vals(vals)
        res = super().write(vals)
        if 'appraisal_eligible' in vals or 'appraisal_admin_score_mode' in vals:
            self._sync_admin_score_exclude()
        return res

    def _sync_admin_score_exclude(self):
        """Mirror the employee-card setting into the Administrative Exclude
        list. ``appraisal.admin.score.exclude`` does the reverse sync on
        create/write/unlink; the context flag stops the two from
        ping-ponging. sudo: HR officers may edit the card without holding
        write access on the configuration list itself."""
        if self.env.context.get('skip_admin_exclude_sync'):
            return
        Exclude = self.env['appraisal.admin.score.exclude'].sudo().with_context(
            skip_admin_exclude_sync=True)
        listed = {
            rec.employee_id.id: rec
            for rec in Exclude.search([('employee_id', 'in', self.ids)])
        }
        to_create = []
        to_unlink = Exclude.browse()
        for employee in self:
            should_be_listed = (
                employee.appraisal_eligible
                and employee.appraisal_admin_score_mode == 'exempt'
            )
            entry = listed.get(employee.id)
            if should_be_listed and not entry:
                to_create.append({'employee_id': employee.id})
            elif entry and not should_be_listed:
                to_unlink |= entry
        if to_create:
            Exclude.create(to_create)
        if to_unlink:
            to_unlink.unlink()

    def action_open_appraisals(self):
        """Open appraisals list for this employee."""
        self.ensure_one()
        return {
            'name': f'Appraisals — {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.appraisal',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_open_skill_timeline(self):
        """Open skill timeline history for the employee."""
        self.ensure_one()
        tree_view = self.env.ref('sl_appraisal.sl_appraisal_skill_history_view_tree')
        graph_view = self.env.ref('sl_appraisal.sl_appraisal_skill_history_view_graph')
        return {
            'name': f'Skill Timeline — {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'appraisal.skill.history',
            'view_mode': 'list,graph',
            'views': [(tree_view.id, 'list'), (graph_view.id, 'graph')],
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
            'target': 'current',
        }

    def action_open_my_employee(self):
        """Override to return current employee's My Info form."""
        employee = self.env.user.employee_id
        if not employee:
            from odoo.exceptions import UserError
            raise UserError("No employee linked to your user.")
        return {
            'name': 'My Info',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'form',
            'res_id': employee.id,
            'view_id': self.env.ref(
                'samalink_security_groups.hr_employee_my_info_form_view').id,
            'target': 'current',
        }
