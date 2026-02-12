from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    requests_limit = fields.Integer(string="Requests Limit (Monthly)", default=3, help="Maximum number of leave requests an employee can make in a month.")
    enable_request_offset = fields.Boolean(string="Notice Required", default=True, help="Enable request notice for leave requests.")
    request_offset = fields.Integer(string="Notice Before (Days)", default=0, help="Number of days to before the leave request.")

    @api.constrains('requests_limit', 'request_offset')
    def _check_positive_values(self):
        for record in self:
            if record.requests_limit < 0:
                raise ValidationError("Requests Limit (Monthly) must be a non-negative integer.")
            if record.request_offset < 0:
                raise ValidationError("Request Before (Days) must be a non-negative integer.")  