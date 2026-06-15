from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError, UserError


class SlBonusBranchProfit(models.Model):
    """Monthly branch / area profitability factor (entered by Finance, approved before use)."""
    _name = 'sl.bonus.branch.profit'
    _description = 'Branch Profitability Factor (Monthly)'
    _order = 'period_start desc, work_location_id'
    _inherit = ['mail.thread']

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    work_location_id = fields.Many2one(
        'hr.work.location', string='Branch',
        required=True, ondelete='restrict',
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, readonly=True,
    )
    department_id = fields.Many2one(
        'hr.department', string='Department',
        help='Optional: tie this profitability record to a department.',
    )
    period_start = fields.Date(
        string='Month', required=True,
        help='First day of the month this factor covers.',
    )
    factor = fields.Float(
        string='Profitability Factor', required=True,
        help='Numeric factor entered by Finance. Tier is derived from this value.',
    )
    tier_id = fields.Many2one(
        'sl.bonus.branch.profit.tier', string='Tier',
        compute='_compute_tier', store=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
    ], default='draft', string='State', tracking=True)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_on = fields.Datetime(string='Approved On', readonly=True)
    note = fields.Text(string='Note')

    _sql_constraints = [
        ('uniq_location_period',
         'unique(work_location_id, period_start)',
         'A profitability factor already exists for this branch and month.'),
    ]

    @api.depends('work_location_id', 'period_start', 'factor')
    def _compute_name(self):
        for rec in self:
            label = rec.work_location_id.name or _('Branch')
            period = rec.period_start and rec.period_start.strftime('%Y-%m') or ''
            rec.name = f"{label} — {period} — {rec.factor:.3f}"

    @api.depends('factor')
    def _compute_tier(self):
        Tier = self.env['sl.bonus.branch.profit.tier'].sudo()
        for rec in self:
            rec.tier_id = Tier.get_tier_for_factor(rec.factor) if rec.factor is not None else False

    def action_approve(self):
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_finance')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_("Only Finance / HR Manager / Admin can approve branch profitability."))
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=self._name, res_id=rec.id,
                action='approve_branch_profit',
                old_value='draft', new_value='approved',
                reason='Approved by user',
            )

    def action_reset_draft(self):
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_finance')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_("Only Finance / HR Manager / Admin can reset branch profitability."))
        for rec in self:
            old = rec.state
            rec.write({'state': 'draft', 'approved_by': False, 'approved_on': False})
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model=self._name, res_id=rec.id,
                action='reset_branch_profit',
                old_value=old, new_value='draft',
                reason='Reset to draft',
            )

    @api.constrains('factor')
    def _check_factor(self):
        for rec in self:
            if rec.factor is None:
                raise ValidationError(_("Profitability factor is required."))

    @api.model
    def find_approved(self, work_location_id, period_date):
        if not work_location_id or not period_date:
            return self.browse()
        first_of_month = fields.Date.from_string(period_date).replace(day=1)
        return self.search([
            ('work_location_id', '=', work_location_id),
            ('period_start', '=', first_of_month),
            ('state', '=', 'approved'),
        ], limit=1)
