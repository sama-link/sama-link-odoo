from odoo import api, fields, models


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
