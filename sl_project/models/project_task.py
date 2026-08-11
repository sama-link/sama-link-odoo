from odoo import models, fields, api, _
from odoo.exceptions import AccessError, ValidationError

# Global (all-users) setting: which task date field the Tasks calendar is
# positioned by. Only stored date/datetime fields can be offered, because the
# calendar range-filters records by this field. See the OWL calendar variant in
# static/src/views/task_calendar/.
CALENDAR_DATE_PARAM = 'sl_project.task_calendar_date_start'
DEFAULT_CALENDAR_DATE_FIELD = 'date_deadline'
ALLOWED_CALENDAR_DATE_FIELDS = [
    'date_deadline',            # Deadline (default)
    'date_assign',             # Assigning Date
    'date_end',                # Ending Date
    'date_last_stage_update',  # Last Stage Update
    'create_date',             # Created On
    'write_date',              # Last Updated On
    'published_date',          # Published Date (sl_project)
]


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Companies the parent project belongs to (for assignee domain).
    project_company_ids = fields.Many2many(
        related='project_id.company_ids',
        string='Project Companies',
        readonly=True,
    )

    published_date = fields.Date(string="Published Date")
    # Mirrors the project's toggle; used only to gate visibility of published_date
    # on the task form (dotted paths can't be used in view `invisible` expressions).
    project_has_published_date = fields.Boolean(
        related='project_id.use_published_date', readonly=True)

    # Assignment control: regular users may only assign tasks within their own
    # org-chart team (subordinates via parent_id chain, coached employees, and
    # themselves). Whoever may edit the project runs it, so they assign anyone
    # in it; project managers and system admins stay unrestricted everywhere.
    allowed_assignee_user_ids = fields.Many2many(
        'res.users', string='Allowed Assignees',
        compute='_compute_allowed_assignee_user_ids')

    @api.depends('project_id')
    @api.depends_context('uid')
    def _compute_allowed_assignee_user_ids(self):
        user = self.env.user
        unrestricted_everywhere = (
            user.has_group('project.group_project_manager')
            or user.has_group('base.group_system'))
        everyone = team = None
        may_manage = {}
        for task in self:
            if unrestricted_everywhere or self._may_manage_project(
                    task.project_id._origin, may_manage):
                if everyone is None:
                    everyone = self.env['res.users'].search(
                        [('share', '=', False), ('active', '=', True)])
                task.allowed_assignee_user_ids = everyone
            else:
                if team is None:
                    team = self._team_assignee_users()
                task.allowed_assignee_user_ids = team

    def _may_manage_project(self, project, cache):
        """Whether the current user runs `project`, i.e. may edit it.

        The manager group carrying project rights is database configuration
        here, not always `project.group_project_manager`: this database drives
        its `ir.rule`s off a manually created "Project / Manger" group that has
        no XML ID, so no group reference in code can recognise it. Write access
        to the project is the same permission those rules express, and it also
        covers a plain user who is the project's own responsible, so ask for
        that instead of naming a group.
        """
        if not project:
            return False
        if project.id not in cache:
            cache[project.id] = project.has_access('write')
        return cache[project.id]

    def _team_assignee_users(self):
        """Current user plus the org-chart team they may assign work to."""
        user = self.env.user
        employee = user.employee_id
        if not employee:
            return user
        # sudo: the searching user may not be allowed to read the whole
        # team hierarchy, but may still assign within it.
        team = self.env['hr.employee'].sudo().search(
            ['|', ('id', 'child_of', employee.id),
                  ('coach_id', '=', employee.id)])
        team_users = team.mapped('user_id').filtered(
            lambda u: u.active and not u.share)
        return self.env['res.users'].browse(team_users.ids) | user

    # ------------------------------------------------------------------
    # Calendar date field (global setting, admin-controlled)
    # ------------------------------------------------------------------
    @api.model
    def _get_calendar_date_field(self):
        """Return the currently configured calendar date field, guarded by the
        whitelist so a stale/invalid parameter can never reach the view."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            CALENDAR_DATE_PARAM, DEFAULT_CALENDAR_DATE_FIELD)
        if value not in ALLOWED_CALENDAR_DATE_FIELDS:
            value = DEFAULT_CALENDAR_DATE_FIELD
        return value

    @api.model
    def get_calendar_date_field_info(self):
        """Read side, callable by any user who can access the calendar.

        Returns the current field, whether the current user may change it, and
        the selectable options (localized labels)."""
        field_defs = self.fields_get(ALLOWED_CALENDAR_DATE_FIELDS, ['string'])
        options = [
            [name, field_defs.get(name, {}).get('string', name)]
            for name in ALLOWED_CALENDAR_DATE_FIELDS
        ]
        return {
            'field': self._get_calendar_date_field(),
            'can_edit': self.env.user.has_group('base.group_system'),
            'options': options,
        }

    @api.model
    def set_calendar_date_field(self, field_name):
        """Write side, admin only. Enforced on the server so the UI's disabled
        state cannot be bypassed via a crafted RPC."""
        if field_name not in ALLOWED_CALENDAR_DATE_FIELDS:
            raise ValidationError(
                _('"%s" is not a valid calendar date field.', field_name))
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(
                _('Only administrators can change the calendar date field.'))
        self.env['ir.config_parameter'].sudo().set_param(
            CALENDAR_DATE_PARAM, field_name)
        return True