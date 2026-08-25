from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Inverse side of sl.qbonus.project.member_employee_ids (same relation table).
    qbonus_project_ids = fields.Many2many(
        'sl.qbonus.project', 'sl_qbonus_project_employee_rel', 'employee_id', 'project_id',
        string='Quarterly Bonus Projects', readonly=True)
    qbonus_project_count = fields.Integer(compute='_compute_qbonus_project_count')

    def _compute_qbonus_project_count(self):
        for employee in self:
            employee.qbonus_project_count = len(employee.qbonus_project_ids)

    def _qbonus_basic_salary(self, on_date=None):
        """Basic salary (contract wage) in force on ``on_date`` — reuses the
        monthly bonus contract lookup so departed employees keep their wage."""
        self.ensure_one()
        contract = self.sudo()._bonus_get_active_contract(on_date=on_date)
        return contract.wage if contract else 0.0

    def action_view_qbonus_projects(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sl_quarter_bonus.action_sl_qbonus_project')
        action['domain'] = [('member_employee_ids', 'in', self.ids)]
        action['context'] = {}
        return action
