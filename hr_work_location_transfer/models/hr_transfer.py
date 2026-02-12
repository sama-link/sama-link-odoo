from odoo import models, fields, api
from odoo.exceptions import ValidationError

class HrTransfer(models.Model):
    _name = 'hr.transfer'
    _inherit = ['mail.thread']
    _description = 'HR Transfer'
    _rec_name = 'employee_id'
    _check_company_auto = True

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    company_id = fields.Many2one('res.company', related='employee_id.company_id', string='Company', store=True)
    date = fields.Date(string='Transfer Date', required=True, default=fields.Date.context_today, tracking=True)
    current_location_id = fields.Many2one('hr.work.location', related='employee_id.work_location_id', string='From Location', store=True, depends=['employee_id'])
    current_parent_id = fields.Many2one('hr.employee', related='employee_id.parent_id', store=True, string='Current Manager', depends=['employee_id'])
    current_leave_manager_id = fields.Many2one('res.users', related='employee_id.leave_manager_id', store=True, string='Current Leave Approver', depends=['employee_id'])
    current_attendance_manager_id = fields.Many2one('res.users', related='employee_id.attendance_manager_id', store=True, string='Current Attendance Approver', depends=['employee_id'])
    new_location_id = fields.Many2one('hr.work.location', string='To Location', required=True, tracking=True)
    new_parent_id = fields.Many2one('hr.employee', string='New Manager', tracking=True)
    new_leave_manager_id = fields.Many2one('res.users', string='New Leave Approver', tracking=True)
    new_attendance_manager_id = fields.Many2one('res.users', string='New Attendance Approver', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        # ('confirmed', 'Confirmed'),
        ('done', 'Transferred'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    reason = fields.Text(string='Reason for Transfer', required=True, tracking=True)

    @api.onchange('new_parent_id')
    def _onchange_new_parent(self):
        for record in self:
            record.new_leave_manager_id = record.new_parent_id.user_id.id
            record.new_attendance_manager_id = record.new_parent_id.user_id.id

    @api.constrains('new_location_id')
    def _check_different_location(self):
        for record in self:
            if record.new_location_id == record.current_location_id:
                raise ValidationError("The new location must be different from the current location.")

    @api.constrains('employee_id')
    def _check_one_request(self):
        for record in self:
            existing_transfers = self.search_count([
                ('employee_id', '=', record.employee_id.id),
                ('state', '=', 'draft'),
                ('id', '!=', record.id)
            ])
            if existing_transfers:
                raise ValidationError("There is already an ongoing transfer request for this employee.")

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_done(self):
        for record in self:
            record.employee_id.work_location_id = record.new_location_id.id
            record.employee_id.address_id = record.new_location_id.address_id.id
            if record.new_parent_id:
                record.employee_id.parent_id = record.new_parent_id.id
                record.employee_id.coach_id = record.new_parent_id.id
            else:
                record.message_post(body="No new manager assigned during transfer.")
            if record.new_leave_manager_id:
                record.employee_id.leave_manager_id = record.new_leave_manager_id.id
            else:
                record.message_post(body="No new leave approver assigned during transfer.")
            if record.new_attendance_manager_id:
                record.employee_id.attendance_manager_id = record.new_attendance_manager_id.id
            else:
                record.message_post(body="No new attendance approver assigned during transfer.")
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})