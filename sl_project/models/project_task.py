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

    company_ids = fields.Many2many(
        'res.company',
        string='Companies (Exclude)',
        domain="[('id', '!=', company_id)]",
        compute='_compute_company_ids', store=True,
        readonly=False, recursive=True, copy=True,
    )

    published_date = fields.Date(string="Published Date")
    # Mirrors the project's toggle; used only to gate visibility of published_date
    # on the task form (dotted paths can't be used in view `invisible` expressions).
    project_has_published_date = fields.Boolean(
        related='project_id.use_published_date', readonly=True)

    # Assignment control: regular users may only assign tasks within their own
    # org-chart team (subordinates via parent_id chain, coached employees, and
    # themselves). Project managers and system admins stay unrestricted.
    allowed_assignee_user_ids = fields.Many2many(
        'res.users', string='Allowed Assignees',
        compute='_compute_allowed_assignee_user_ids')

    @api.depends_context('uid')
    def _compute_allowed_assignee_user_ids(self):
        user = self.env.user
        if (user.has_group('project.group_project_manager')
                or user.has_group('base.group_system')):
            allowed = self.env['res.users'].search(
                [('share', '=', False), ('active', '=', True)])
        else:
            allowed = user
            employee = user.employee_id
            if employee:
                # sudo: the searching user may not be allowed to read the whole
                # team hierarchy, but may still assign within it.
                team = self.env['hr.employee'].sudo().search(
                    ['|', ('id', 'child_of', employee.id),
                          ('coach_id', '=', employee.id)])
                team_users = team.mapped('user_id').filtered(
                    lambda u: u.active and not u.share)
                allowed = self.env['res.users'].browse(team_users.ids) | user
        for task in self:
            task.allowed_assignee_user_ids = allowed

    @api.depends('project_id.company_ids', 'parent_id.company_ids')
    def _compute_company_ids(self):
        for task in self:
            if not task.parent_id and not task.project_id:
                continue
            task.company_ids = task.project_id.company_ids or task.parent_id.company_ids

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