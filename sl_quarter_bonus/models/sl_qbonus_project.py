from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

PROJECT_STATES = [
    ('draft', 'Draft'),
    ('approved', 'Approved'),
    ('in_progress', 'In Progress'),
    ('submitted', 'Submitted'),
    ('received', 'Received'),
    ('cancelled', 'Cancelled'),
]
SPLIT_METHODS = [
    ('equal', 'Equal split'),
    ('ratio', 'Split by ratio'),
    ('manual', 'Manual points'),
]
# Fields only a Project Admin may set. State moves through the action buttons,
# which pass the ``qbonus_workflow`` context so owners can still start/submit.
ADMIN_WRITE_FIELDS = {
    'quarter_id', 'points_approved', 'kpi_achievement_pct', 'points_late_penalty',
    'bonus_quarter_id', 'date_received', 'state', 'late_alert_date',
}
ADMIN_CREATE_FIELDS = {
    'points_approved', 'kpi_achievement_pct', 'points_late_penalty',
    'bonus_quarter_id', 'date_received',
}


class SlQbonusProject(models.Model):
    _name = 'sl.qbonus.project'
    _description = 'Quarterly Bonus Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_end desc, id desc'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    owner_id = fields.Many2one(
        'hr.employee', string='Project Owner', required=True, tracking=True, index=True,
        default=lambda self: self.env.user.employee_id)
    owner_user_id = fields.Many2one(
        'res.users', related='owner_id.user_id', store=True, index=True)
    date_start = fields.Date(
        string='Start Date', required=True, tracking=True,
        default=fields.Date.context_today)
    date_end = fields.Date(string='End Date', required=True, tracking=True)
    duration_months = fields.Float(
        string='Time Frame (months)', compute='_compute_duration_months',
        store=True, digits=(16, 2))
    quarter_id = fields.Many2one(
        'sl.qbonus.quarter', string='Target Quarter', required=True, index=True,
        tracking=True, default=lambda self: self._default_quarter(),
        help='The quarter the admin expects this project to be received in. '
             'Defaults to the current quarter. A project not received by the '
             'end of its target quarter is late.')
    bonus_quarter_id = fields.Many2one(
        'sl.qbonus.quarter', string='Bonus Quarter', readonly=True, copy=False, index=True,
        help='The quarter whose pool pays this project: the quarter in which '
             'the admin received it.')
    bonus_quarter_state = fields.Selection(related='bonus_quarter_id.state')
    kpi_description = fields.Text(string='KPI Target')
    kpi_achievement_pct = fields.Float(
        string='KPI Achieved %', default=100.0, digits=(5, 2), tracking=True,
        help='Recorded by the admin at reception. Points earned = approved '
             'points x KPI achieved % - late penalty.')
    points_approved = fields.Float(
        string='Approved Points', digits=(16, 2), tracking=True)
    points_late_penalty = fields.Float(
        string='Late Penalty (points)', digits=(16, 2), tracking=True, copy=False)
    points_earned = fields.Float(
        string='Points Earned', compute='_compute_points_earned', store=True, digits=(16, 2))
    split_method = fields.Selection(SPLIT_METHODS, default='equal', required=True)
    owner_share_pct = fields.Float(
        string='Owner Share %', digits=(5, 2), default=0.0,
        help='Share of the project points kept by the owner before the rest '
             'is split among the team.')
    member_line_ids = fields.One2many(
        'sl.qbonus.project.member', 'project_id', string='Team & Points', copy=False)
    member_user_ids = fields.Many2many(
        'res.users', 'sl_qbonus_project_user_rel', 'project_id', 'user_id',
        string='Team Users', compute='_compute_members', store=True)
    member_employee_ids = fields.Many2many(
        'hr.employee', 'sl_qbonus_project_employee_rel', 'project_id', 'employee_id',
        string='Team', compute='_compute_members', store=True)
    points_distributed = fields.Float(
        compute='_compute_points_distributed', digits=(16, 2))
    points_undistributed = fields.Float(
        compute='_compute_points_distributed', digits=(16, 2))
    task_ids = fields.One2many('sl.qbonus.task', 'project_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_counts')
    open_task_count = fields.Integer(compute='_compute_task_counts')
    state = fields.Selection(
        PROJECT_STATES, default='draft', required=True, tracking=True, index=True, copy=False)
    date_submitted = fields.Date(readonly=True, copy=False)
    date_received = fields.Date(readonly=True, copy=False, tracking=True)
    is_late = fields.Boolean(
        string='Late', compute='_compute_is_late', search='_search_is_late',
        help='Not received by the end of its target quarter.')
    late_alert_date = fields.Date(copy=False)
    color = fields.Integer()
    description = fields.Html()

    # ------------------------------------------------------------------
    # Defaults / helpers
    # ------------------------------------------------------------------
    @api.model
    def _default_quarter(self):
        return self.env['sl.qbonus.quarter']._get_or_create(
            self.env.company, fields.Date.context_today(self)).id

    @api.model
    def _late_penalty_pct(self):
        return float(self.env['ir.config_parameter'].sudo().get_param(
            'sl_quarter_bonus.late_penalty_pct', 10.0) or 0.0)

    def _is_admin(self):
        user = self.env.user
        return (self.env.su or user.has_group('sl_quarter_bonus.group_qbonus_admin')
                or user.has_group('base.group_system'))

    def _check_admin(self):
        if not self._is_admin():
            raise AccessError(_('Only a Project Admin can do this.'))

    def _check_owner_or_admin(self):
        if self._is_admin():
            return
        for p in self:
            if p.owner_user_id != self.env.user:
                raise AccessError(_('Only the owner of "%s" or a Project Admin can do this.') % p.name)

    def _guard_admin_fields(self, vals, create=False):
        if self._is_admin() or self.env.context.get('qbonus_workflow'):
            return
        touched = set(vals) & (ADMIN_CREATE_FIELDS if create else ADMIN_WRITE_FIELDS)
        if not create and 'quarter_id' in touched and all(p.state == 'draft' for p in self):
            touched.discard('quarter_id')
        if create:
            touched = {
                f for f in touched
                if vals.get(f) not in (False, None, 0, 0.0)
                and not (f == 'kpi_achievement_pct' and vals.get(f) == 100)
            }
        if touched:
            labels = ', '.join(self._fields[f].string for f in sorted(touched))
            raise AccessError(_('Only a Project Admin can set: %s.') % labels)

    def _ensure_owner_line(self):
        Member = self.env['sl.qbonus.project.member'].sudo()
        for p in self:
            lines = p.member_line_ids.sudo()
            stale = lines.filtered(lambda l: l.role == 'owner' and l.employee_id != p.owner_id)
            if stale:
                stale.write({'role': 'member'})
            current = lines.filtered(lambda l: l.employee_id == p.owner_id)
            if current:
                current.filtered(lambda l: l.role != 'owner').write({'role': 'owner'})
            elif p.owner_id:
                Member.create({'project_id': p.id, 'employee_id': p.owner_id.id, 'role': 'owner'})

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('date_start', 'date_end')
    def _compute_duration_months(self):
        for p in self:
            if p.date_start and p.date_end and p.date_end >= p.date_start:
                days = (p.date_end - p.date_start).days + 1
                p.duration_months = round(days / 30.4375, 2)
            else:
                p.duration_months = 0.0

    @api.depends('points_approved', 'kpi_achievement_pct', 'points_late_penalty', 'state')
    def _compute_points_earned(self):
        for p in self:
            if p.state == 'cancelled':
                p.points_earned = 0.0
                continue
            earned = (p.points_approved or 0.0) * (p.kpi_achievement_pct or 0.0) / 100.0
            earned -= p.points_late_penalty or 0.0
            p.points_earned = max(round(earned, 2), 0.0)

    @api.depends('member_line_ids.employee_id', 'member_line_ids.user_id', 'owner_id', 'owner_id.user_id')
    def _compute_members(self):
        for p in self:
            employees = p.member_line_ids.mapped('employee_id') | p.owner_id
            p.member_employee_ids = employees
            p.member_user_ids = employees.mapped('user_id')

    @api.depends('member_line_ids.points', 'points_earned')
    def _compute_points_distributed(self):
        for p in self:
            distributed = sum(p.member_line_ids.mapped('points'))
            p.points_distributed = distributed
            p.points_undistributed = p.points_earned - distributed

    @api.depends('task_ids.stage')
    def _compute_task_counts(self):
        for p in self:
            p.task_count = len(p.task_ids)
            p.open_task_count = len(p.task_ids.filtered(lambda t: t.stage not in ('done', 'cancelled')))

    @api.depends('state', 'date_received', 'quarter_id.date_end')
    def _compute_is_late(self):
        today = fields.Date.context_today(self)
        for p in self:
            end = p.quarter_id.date_end
            if not end or p.state == 'cancelled':
                p.is_late = False
            elif p.state == 'received':
                p.is_late = bool(p.date_received and p.date_received > end)
            else:
                p.is_late = today > end

    def _search_is_late(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(_('Unsupported operator for Late: %s') % operator)
        want_late = (operator == '=') == bool(value)
        today = fields.Date.context_today(self)
        past_quarters = self.env['sl.qbonus.quarter'].sudo().search([('date_end', '<', today)]).ids
        received = self.search([('state', '=', 'received')])
        late_received = received.filtered(
            lambda p: p.date_received and p.quarter_id.date_end and p.date_received > p.quarter_id.date_end).ids
        domain = [
            '|',
            '&', ('state', 'not in', ('received', 'cancelled')), ('quarter_id', 'in', past_quarters),
            ('id', 'in', late_received),
        ]
        return domain if want_late else ['!'] + domain

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for p in self:
            if p.date_start and p.date_end and p.date_end < p.date_start:
                raise ValidationError(_('The end date must be after the start date.'))

    @api.constrains('points_approved', 'kpi_achievement_pct', 'points_late_penalty', 'owner_share_pct')
    def _check_numbers(self):
        for p in self:
            if p.points_approved < 0 or p.points_late_penalty < 0:
                raise ValidationError(_('Points cannot be negative.'))
            if not 0 <= p.kpi_achievement_pct <= 100:
                raise ValidationError(_('KPI achieved % must be between 0 and 100.'))
            if not 0 <= p.owner_share_pct <= 100:
                raise ValidationError(_('Owner share % must be between 0 and 100.'))

    @api.constrains('member_line_ids', 'points_earned')
    def _check_points_total(self):
        for p in self:
            total = sum(p.member_line_ids.mapped('points'))
            if float_compare(total, p.points_earned, precision_digits=2) > 0:
                raise ValidationError(_(
                    'Distributed points (%.2f) exceed the points the project earned (%.2f).'
                ) % (total, p.points_earned))

    @api.constrains('quarter_id', 'company_id')
    def _check_quarter_company(self):
        for p in self:
            if p.quarter_id and p.quarter_id.company_id != p.company_id:
                raise ValidationError(_('The target quarter belongs to another company.'))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id and (not self.quarter_id or self.quarter_id.company_id != self.company_id):
            self.quarter_id = self.env['sl.qbonus.quarter']._get_or_create(
                self.company_id, fields.Date.context_today(self))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._guard_admin_fields(vals, create=True)
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('sl.qbonus.project') or 'New'
        projects = super().create(vals_list)
        projects._ensure_owner_line()
        return projects

    def write(self, vals):
        self._guard_admin_fields(vals)
        if not self.env.su and not self.env.context.get('qbonus_workflow'):
            locked = self.filtered(lambda p: p.bonus_quarter_id.state == 'closed')
            if locked:
                raise UserError(_('Quarter %s is closed: its projects are locked.')
                                % ', '.join(locked.mapped('bonus_quarter_id.name')))
        res = super().write(vals)
        if 'owner_id' in vals:
            self._ensure_owner_line()
        return res

    def unlink(self):
        if any(p.state not in ('draft', 'cancelled') for p in self):
            raise UserError(_('Only draft or cancelled projects can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _workflow_write(self, vals):
        return self.with_context(qbonus_workflow=True).write(vals)

    def action_approve(self):
        self._check_admin()
        for p in self:
            if p.state != 'draft':
                continue
            if float_is_zero(p.points_approved, precision_digits=2):
                raise UserError(_('Set the approved points for "%s" before approving it.') % p.name)
            p._ensure_owner_line()
            p._workflow_write({'state': 'approved'})
        return True

    def action_start(self):
        self._check_owner_or_admin()
        self.filtered(lambda p: p.state == 'approved')._workflow_write({'state': 'in_progress'})
        return True

    def action_submit(self):
        self._check_owner_or_admin()
        today = fields.Date.context_today(self)
        for p in self:
            if p.state != 'in_progress':
                continue
            if p.open_task_count:
                raise UserError(_('%d task(s) of "%s" are still open. Close them before submitting.')
                                % (p.open_task_count, p.name))
            vals = {'state': 'submitted', 'date_submitted': today}
            if p.is_late and float_is_zero(p.points_late_penalty, precision_digits=2):
                vals['points_late_penalty'] = round(p.points_approved * p._late_penalty_pct() / 100.0, 2)
            p._workflow_write(vals)
            if p.is_late:
                p.message_post(body=_('Submitted after the end of its target quarter %s: '
                                      'a late penalty of %s points was suggested.')
                               % (p.quarter_id.name, vals.get('points_late_penalty', p.points_late_penalty)))
        return True

    def action_return(self):
        self._check_admin()
        self.filtered(lambda p: p.state == 'submitted')._workflow_write({'state': 'in_progress'})
        return True

    def action_receive(self):
        self._check_admin()
        today = fields.Date.context_today(self)
        Quarter = self.env['sl.qbonus.quarter']
        for p in self:
            if p.state != 'submitted':
                continue
            quarter = Quarter._get_or_create(p.company_id, today)
            if quarter.state == 'closed':
                raise UserError(_('Quarter %s is already closed; reopen it to receive "%s".')
                                % (quarter.name, p.name))
            p._workflow_write({
                'state': 'received',
                'date_received': today,
                'bonus_quarter_id': quarter.id,
            })
            body = _('Received with KPI %s%% -> %s points earned, paid from %s.') % (
                p.kpi_achievement_pct, p.points_earned, quarter.name)
            if quarter != p.quarter_id:
                body += ' ' + _('(Target quarter was %s.)') % p.quarter_id.name
            p.message_post(body=body)
        return True

    def action_cancel(self):
        self._check_admin()
        self.filtered(lambda p: p.state not in ('received', 'cancelled'))._workflow_write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        self._check_admin()
        for p in self:
            if p.bonus_quarter_id and p.bonus_quarter_id.state == 'closed':
                raise UserError(_('Quarter %s is closed; reopen it first.') % p.bonus_quarter_id.name)
            p._workflow_write({
                'state': 'draft',
                'date_received': False,
                'date_submitted': False,
                'bonus_quarter_id': False,
                'late_alert_date': False,
            })
        return True

    def action_distribute(self):
        """Fill the member points from the split method."""
        self._check_owner_or_admin()
        for p in self:
            if p.state != 'received':
                raise UserError(_('Points of "%s" can only be distributed after the project is received.') % p.name)
            if p.bonus_quarter_id.state == 'closed':
                raise UserError(_('Quarter %s is closed.') % p.bonus_quarter_id.name)
            earned = p.points_earned
            owner_line = p.member_line_ids.filtered(lambda l: l.role == 'owner')
            members = p.member_line_ids - owner_line
            owner_points = round(earned * p.owner_share_pct / 100.0, 2) if members else earned
            rest = earned - owner_points
            if p.split_method == 'ratio':
                total_ratio = sum(members.mapped('ratio_pct'))
                if members and float_is_zero(total_ratio, precision_digits=2):
                    raise UserError(_('Enter a ratio % for the team members of "%s" first.') % p.name)
                for line in members:
                    line.points = round(rest * line.ratio_pct / total_ratio, 2)
            elif p.split_method == 'equal':
                for line in members:
                    line.points = round(rest / len(members), 2)
            # 'manual': member points are typed in directly; only the owner line follows the share.
            if owner_line:
                owner_line.points = owner_points
            p.message_post(body=_('Points distributed (%s): owner %s, team %s of %s earned.') % (
                dict(SPLIT_METHODS)[p.split_method], owner_points,
                sum(members.mapped('points')), earned))
        return True

    def action_view_tasks(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sl_quarter_bonus.action_sl_qbonus_task')
        action['domain'] = [('project_id', '=', self.id)]
        action['context'] = {'default_project_id': self.id, 'search_default_group_stage': 1}
        return action

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_late_alerts(self):
        """Flag newly late projects: chatter note + to-do for every Project
        Admin of the company. Runs daily; each project is alerted once."""
        admins = self.env.ref('sl_quarter_bonus.group_qbonus_admin').users.filtered('active')
        projects = self.sudo().search([
            ('state', 'not in', ('received', 'cancelled')),
            ('late_alert_date', '=', False),
            ('is_late', '=', True),
        ])
        today = fields.Date.context_today(self)
        for p in projects:
            p.message_post(body=_('LATE: not received by the end of target quarter %s. '
                                  'A late penalty applies and the bonus moves to the quarter of reception.')
                           % p.quarter_id.name)
            for user in admins.filtered(lambda u: p.company_id in u.company_ids):
                p.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=_('Late project: %s') % p.name,
                    note=_('The project was not received by %s. Review the late penalty when it is submitted.')
                    % p.quarter_id.date_end)
            p.late_alert_date = today
        return True
