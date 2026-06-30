from odoo import api, fields, models


class SlFreelancerTask(models.Model):
    _name = 'sl.freelancer.task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Freelancer Work Record'
    _rec_name = 'employee_id'
    _order = 'date desc, id desc'
    _check_company_auto = True

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, check_company=True,
        default=lambda self: self.env.user.employee_id.id, tracking=True)
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id',
        string='Company', store=True)
    description = fields.Text(string='Description', tracking=True)
    attendance_ids = fields.Many2many(
        'hr.attendance',
        'sl_freelancer_task_attendance_rel', 'task_id', 'attendance_id',
        string='Attendance Records', check_company=True,
        domain="[('employee_id', '=', employee_id)]",
        help="Attendance punch records selected for this freelancer task.")
    total_hours = fields.Float(
        string='Total Hours', compute='_compute_total_hours', store=True,
        help="Sum of the worked hours of the selected attendance records.")
    attendance_count = fields.Integer(
        string='Attendance Count', compute='_compute_attendance_count', store=True)
    can_edit_employee = fields.Boolean(
        string='Can Edit Employee', compute='_compute_can_edit_employee')
    date = fields.Date(string='Date', default=fields.Date.today, tracking=True)
    active = fields.Boolean(default=True)

    @api.depends('attendance_ids.worked_hours')
    def _compute_total_hours(self):
        for record in self:
            record.total_hours = sum(record.attendance_ids.mapped('worked_hours'))

    @api.depends('attendance_ids')
    def _compute_attendance_count(self):
        for record in self:
            record.attendance_count = len(record.attendance_ids)

    def _compute_can_edit_employee(self):
        # Administrators (module admins or the technical system admin) pick the
        # employee; plain self-service users get their own, read-only.
        is_admin = (
            self.env.user.has_group('sl_freelancer.group_sl_freelancer_admin')
            or self.env.user.has_group('base.group_system'))
        for record in self:
            record.can_edit_employee = is_admin

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Drop any selected attendances that no longer match the employee."""
        for record in self:
            record.attendance_ids = record.attendance_ids.filtered(
                lambda a: a.employee_id == record.employee_id)

    def action_open_attendances(self):
        """Smart button: open the attendance records selected on this task."""
        self.ensure_one()
        return {
            'name': f'Attendances — {self.employee_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.attendance',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.attendance_ids.ids)],
        }
