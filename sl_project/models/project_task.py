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