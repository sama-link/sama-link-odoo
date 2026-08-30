from odoo import _, api, fields, models

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
        help="'No administrative score': the employee's appraisals always "
             "receive a 100% administration score, regardless of absences, "
             "lateness or penalties.",
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

    @api.model
    def _period_review_scope(self, company, date_from, date_to, extra_domain=None):
        """Employees a batch wizard should scan for period issues: active
        ones matching ``extra_domain`` in ``company`` (or no company), plus
        departed (archived) ones who still held a contract during the
        period. Ex-employees who left before the period are not included,
        otherwise every past employee would be flagged as 'no contract'."""
        base = list(extra_domain or []) + [
            ('company_id', 'in', [company.id, False]),
        ]
        active = self.search(base)
        contract_emp_ids = self.env['hr.contract'].sudo().with_context(
            active_test=False,
        ).search([
            ('state', 'in', ('open', 'close')),
            ('date_start', '<=', date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', date_from),
        ]).mapped('employee_id').ids
        departed = self.with_context(active_test=False).search(
            base + [('active', '=', False), ('id', 'in', contract_emp_ids)])
        return active | departed

    def _period_contract_issues(self, date_from, date_to):
        """Contract problems of these employees inside [date_from, date_to].

        Returns ``{employee_id: {'contracts', 'boundary', 'no_contract',
        'summary'}}`` — only for employees with a problem:
        - ``boundary``: contracts (recordset) that start or end inside the
          period (hired / departed / renewed mid-period);
        - ``no_contract``: no running/closed contract overlaps the period.
        Shared by the appraisal and bonus batch review wizards.
        """
        if not self or not date_from or not date_to:
            return {}
        Contract = self.env['hr.contract'].sudo().with_context(active_test=False)
        contracts_by_emp = {}
        for contract in Contract.search([
            ('employee_id', 'in', self.ids),
            ('state', 'in', ('open', 'close')),
            ('date_start', '<=', date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', date_from),
        ]):
            contracts_by_emp.setdefault(contract.employee_id.id, Contract.browse())
            contracts_by_emp[contract.employee_id.id] |= contract

        issues = {}
        for employee in self:
            contracts = contracts_by_emp.get(employee.id, Contract.browse())
            boundary = contracts.filtered(
                lambda c: c.date_start > date_from
                or (c.date_end and c.date_end < date_to))
            no_contract = not contracts
            if not (boundary or no_contract):
                continue
            summary = []
            for contract in boundary:
                if contract.date_start > date_from:
                    summary.append(_("Contract starts %s") % contract.date_start)
                if contract.date_end and contract.date_end < date_to:
                    summary.append(_("Contract ends %s") % contract.date_end)
            if no_contract:
                summary.append(_("No active contract in the period"))
            issues[employee.id] = {
                'contracts': contracts,
                'boundary': boundary,
                'no_contract': no_contract,
                'summary': "; ".join(summary),
            }
        return issues

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

    # ── Appraisal eligibility normalization ──────────────────────────
    # The card is the single source of truth: hr.appraisal's administration
    # scores depend directly on appraisal_admin_score_mode, so changing the
    # select recomputes the related appraisal scores through the ORM.
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
        return super().create(vals_list)

    def write(self, vals):
        self._normalize_appraisal_eligibility_vals(vals)
        return super().write(vals)

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
