from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    requests_limit = fields.Integer(
        string="Requests Limit (Monthly)",
        default=3,
        help="Maximum number of separate leave requests (records) an employee can make in a calendar month for this type—not total days.",
    )
    monthly_days_limit = fields.Float(
        string="Total Days Limit (Monthly)",
        default=0.0,
        digits=(16, 2),
        help="Maximum sum of time off days in one calendar month for this type (0 = no cap). Counts overlapping requests, including a single long request.",
    )
    enable_request_offset = fields.Boolean(string="Notice Required", default=True, help="Enable request notice for leave requests.")
    request_offset = fields.Integer(string="Notice Before (Days)", default=0, help="Number of days to before the leave request.")

    @api.constrains('requests_limit', 'request_offset', 'monthly_days_limit')
    def _check_positive_values(self):
        for record in self:
            if record.requests_limit < 0:
                raise ValidationError("Requests Limit (Monthly) must be a non-negative integer.")
            if record.request_offset < 0:
                raise ValidationError("Request Before (Days) must be a non-negative integer.")
            if record.monthly_days_limit < 0:
                raise ValidationError("Total Days Limit (Monthly) must be zero or positive.")