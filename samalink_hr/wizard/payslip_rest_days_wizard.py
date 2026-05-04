from babel.dates import format_date as babel_format_date

from odoo import models, fields, api


class HrPayslipRestDaysWizard(models.TransientModel):
    _name = 'hr.payslip.rest.days.wizard'
    _description = 'Rest days in payslip period'

    payslip_id = fields.Many2one('hr.payslip', string='Payslip', required=True, readonly=True)
    line_ids = fields.One2many(
        'hr.payslip.rest.days.wizard.line', 'wizard_id', string='Rest days', readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        payslip_id = self.env.context.get('default_payslip_id')
        if payslip_id:
            if 'payslip_id' in fields_list:
                res['payslip_id'] = payslip_id
            if 'line_ids' in fields_list:
                slip = self.env['hr.payslip'].browse(payslip_id)
                res['line_ids'] = [
                    (0, 0, {'rest_date': d})
                    for d in slip._samalink_get_scheduled_rest_dates()
                ]
        return res


class HrPayslipRestDaysWizardLine(models.TransientModel):
    _name = 'hr.payslip.rest.days.wizard.line'
    _description = 'Rest day line (payslip wizard)'

    wizard_id = fields.Many2one('hr.payslip.rest.days.wizard', required=True, ondelete='cascade')
    rest_date = fields.Date(string='Date', required=True)
    weekday_label = fields.Char(string='Day', compute='_compute_weekday_label')

    @api.depends('rest_date')
    def _compute_weekday_label(self):
        for line in self:
            if not line.rest_date:
                line.weekday_label = ''
                continue
            lang = (line.env.context.get('lang') or 'en_US').replace('-', '_')
            try:
                line.weekday_label = babel_format_date(line.rest_date, 'EEEE', locale=lang)
            except Exception:
                line.weekday_label = line.rest_date.strftime('%A')
