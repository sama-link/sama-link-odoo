from odoo import http
from odoo.http import request
from werkzeug.exceptions import BadRequest, NotFound, Unauthorized


class PayslipAccessController(http.Controller):
    @http.route('/payslip/<string:token>', auth='public', website=True)
    def access_payslip(self, token):
        lang = request.params.get('lang', 'en_US')
        report_type = request.params.get('type', 'pdf')
        payslip = request.env['hr.payslip'].sudo().search([('token', '=', token)], limit=1)
        if not payslip:
            raise Unauthorized()
        report = request.env["ir.actions.report"].with_context(lang=lang or "en_US").sudo()._render_qweb_pdf('payslip_share.hr_payslip_report_action_simple', [payslip.id], data={'report_type': 'pdf'})[0]
        return request.make_response(report, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(report)),
        ])