from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrIncentive(models.Model):
    _name = 'hr.incentive'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'HR Incentive'
    _rec_name = 'employee_id'
    _check_company_auto = True

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    company_id = fields.Many2one('res.company', related='employee_id.company_id', string='Company', store=True)
    current_contract_id = fields.Many2one('hr.contract', related='employee_id.contract_id', string='Contract', store=True)
    type = fields.Selection([
        ('bonus', 'Bonus'),
        ('penalty', 'Penalty')
    ], string='Incentive Type', required=True, default='bonus')
    based_on = fields.Selection([
        ('days', 'Days'),
        ('amount', 'Amount')
    ], string='Based On', required=True, default='days', tracking=True)
    days = fields.Float(string='Days', tracking=True)
    amount = fields.Float(string='Amount', compute="_compute_amount", store=True, readonly=False, tracking=True)
    date = fields.Date(string='Date', default=fields.Date.today, tracking=True)
    description = fields.Text(string='Description', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'First Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    work_location_id = fields.Many2one(related="employee_id.work_location_id", domain="[('address_id', '=', address_id)]")
    active = fields.Boolean(default=True, tracking=True)
    deleted = fields.Boolean(default=False)

    def action_archive(self):
        for record in self:
            if record.state not in ['draft', 'cancelled']:
                raise ValidationError("You cannot delete an incentive which is not in draft or cancelled state.")
        return super(HrIncentive, self).action_archive()

    def action_unarchive(self):
        for record in self:
            if record.deleted:
                raise ValidationError("You cannot unarchive a deleted incentive.")
        return super(HrIncentive, self).action_unarchive()

    def unlink(self):
        for record in self:
            if record.state not in ['draft', 'cancelled']:
                raise ValidationError("You cannot delete an incentive which is not in draft or cancelled state.")
        self.write({'active': False, 'deleted': True})
        for record in self:
            record.message_post(body="Incentive record has been deleted.")
        return True

    @api.depends('type', 'days', 'current_contract_id.wage')
    def _compute_amount(self):
        for record in self:
            if record.based_on == 'days' and record.days > 0:
                day_rate = record.current_contract_id.wage / 30 if record.current_contract_id else 0
                amount = record.days * day_rate
                if record.type == 'bonus':
                    record.amount = amount
                elif record.type == 'penalty':
                    record.amount = -amount

    @api.constrains('days', 'amount')
    def _check_days_amount(self):
        for record in self:
            if record.based_on == 'days' and record.days <= 0:
                raise ValidationError("Days must be positive when based on days.")
            if record.based_on == 'amount' and record.amount == 0:
                raise ValidationError("Amount must not be zero when based on amount.")

    @api.constrains('employee_id')
    def _check_current_wage(self):
        for record in self:
            if not record.current_contract_id or record.current_contract_id.wage <= 0:
                raise ValidationError("The employee must have a current contract with a positive wage.")

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_validate(self):
        self.write({'state': 'validated'})

    def action_approve(self):
        if not self.env.user.has_group('hr_incentives.group_hr_incentives_manager'):
            self.action_validate()
        else:
            self.write({'state': 'approved'})

    def action_refuse(self):
        self.write({'state': 'rejected'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})