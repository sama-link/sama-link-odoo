import uuid
from odoo import models, fields, api, _


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    token = fields.Char(default=lambda self: str(uuid.uuid4()))
    access_url = fields.Char(string='Access URL', compute='_compute_access_url', store=True)

    def get_report_summary(self):
        return {
            _('Earnings'): sum(self.details_by_salary_rule_category_ids.filtered(lambda x: x.total > 0 and x.code not in ['NET', 'BASIC_SALARY']).mapped('total')),
            _('Deductions'): sum(self.details_by_salary_rule_category_ids.filtered(lambda x: x.total < 0).mapped('total')),
            _('Net'): self.details_by_salary_rule_category_ids.filtered(lambda x: x.code == 'NET').total,
        }

    def generate_access_token(self):
        for payslip in self:
            payslip.token = str(uuid.uuid4())

    @api.depends('token')
    def _compute_access_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for payslip in self:
            payslip.access_url = payslip.get_report_url(base_url)

    def get_report_url(self, base_url):
        self.ensure_one()
        return f"{base_url}/payslip/{self.token}?lang=ar_001&type=pdf"