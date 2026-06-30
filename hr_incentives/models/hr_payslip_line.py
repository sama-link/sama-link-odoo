from odoo import models


class HrPayslipLine(models.Model):
    _inherit = 'hr.payslip.line'

    # Incentive-backed salary rules and the incentive type shown in their linked list.
    _INCENTIVE_RULE_TYPES = {
        'INCENTIV': 'bonus',         # "Rewards" rule -> show bonuses only
        'ADMIN_PENALTY': 'penalty',  # "Administrative penalties" rule -> show penalties
    }

    def _incentive_linked_domain(self, line):
        slip = line.slip_id
        return [
            ('employee_id', '=', slip.employee_id.id),
            ('date', '>=', slip.date_from),
            ('date', '<=', slip.date_to),
            ('state', '=', 'approved'),
            ('payment_type', '=', 'with_salary'),
            ('type', '=', self._INCENTIVE_RULE_TYPES[line.salary_rule_id.code]),
        ]

    def _compute_related_records_count(self):
        for line in self:
            if line.salary_rule_id.code not in self._INCENTIVE_RULE_TYPES:
                super(HrPayslipLine, line)._compute_related_records_count()
                continue
            count = self.env['hr.incentive'].search_count(self._incentive_linked_domain(line))
            line.update({'related_records_count': count})

    def open_related_records(self):
        self.ensure_one()
        if self.salary_rule_id.code not in self._INCENTIVE_RULE_TYPES:
            return super(HrPayslipLine, self).open_related_records()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "hr_incentives.action_hr_incentives_payslip"
        )
        action['domain'] = self._incentive_linked_domain(self)
        return action
