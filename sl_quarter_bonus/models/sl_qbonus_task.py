from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

TASK_STAGES = [
    ('todo', 'To Do'),
    ('doing', 'In Progress'),
    ('done', 'Done'),
    ('cancelled', 'Cancelled'),
]


class SlQbonusTask(models.Model):
    _name = 'sl.qbonus.task'
    _description = 'Quarterly Bonus Project Task'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, date_deadline, id'

    name = fields.Char(required=True, tracking=True)
    project_id = fields.Many2one(
        'sl.qbonus.project', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    project_state = fields.Selection(related='project_id.state')
    owner_user_id = fields.Many2one(related='project_id.owner_user_id', store=True)
    assignee_id = fields.Many2one(
        'hr.employee', string='Assigned To', tracking=True, index=True)
    assignee_user_id = fields.Many2one(related='assignee_id.user_id', store=True)
    project_member_ids = fields.Many2many(
        related='project_id.member_employee_ids', string='Project Team')
    date_start = fields.Date(string='Start Date')
    date_deadline = fields.Date(string='Deadline', tracking=True)
    stage = fields.Selection(TASK_STAGES, default='todo', required=True, tracking=True, index=True)
    priority = fields.Selection([('0', 'Normal'), ('1', 'High')], default='0')
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    description = fields.Html()
    is_overdue = fields.Boolean(compute='_compute_is_overdue')

    @api.depends('date_deadline', 'stage')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for task in self:
            task.is_overdue = bool(
                task.date_deadline and task.date_deadline < today
                and task.stage not in ('done', 'cancelled'))

    @api.constrains('assignee_id', 'project_id')
    def _check_assignee(self):
        for task in self:
            if not task.assignee_id:
                continue
            project = task.project_id.sudo()
            if task.assignee_id not in (project.member_employee_ids | project.owner_id):
                raise ValidationError(_(
                    '%s is not on the team of "%s". Add them under Team & Points first.'
                ) % (task.assignee_id.name, project.name))

    def _check_project_open(self):
        if self.env.su or self.env.user.has_group('sl_quarter_bonus.group_qbonus_admin'):
            return
        locked = self.filtered(lambda t: t.project_id.state in ('received', 'cancelled'))
        if locked:
            raise UserError(_('Project "%s" is %s: its tasks are locked.')
                            % (locked[0].project_id.name, locked[0].project_id.state))

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks._check_project_open()
        return tasks

    def write(self, vals):
        self._check_project_open()
        return super().write(vals)

    def unlink(self):
        self._check_project_open()
        return super().unlink()
