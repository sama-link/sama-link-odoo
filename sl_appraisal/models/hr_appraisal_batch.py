from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class HrAppraisalBatch(models.Model):
    _name = 'hr.appraisal.batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Appraisal Batches'
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('published', 'Published'),
            ('submitted', 'Submitted'),
            ('hr_finalization', 'HR Finalization'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        copy=False,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        copy=False,
    )
    date_deadline = fields.Date(string='Appraisal Deadline', required=True)
    date_from = fields.Date(string='Period From', required=True)
    date_to = fields.Date(string='Period To', required=True)
    creator_id = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    appraisal_ids = fields.One2many(
        'hr.appraisal',
        'appraisal_batch_id',
        string='Appraisals',
    )
    appraisal_count = fields.Integer(
        string='Appraisal Count',
        compute='_compute_appraisal_count',
    )
    is_appraisal_admin = fields.Boolean(
        compute='_compute_is_appraisal_admin',
    )

    @api.depends('appraisal_ids')
    def _compute_appraisal_count(self):
        for batch in self:
            batch.appraisal_count = len(batch.appraisal_ids)

    @api.depends_context('uid')
    def _compute_is_appraisal_admin(self):
        is_admin = (
            self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        )
        for batch in self:
            batch.is_appraisal_admin = is_admin

    @api.constrains('date_from', 'date_to', 'date_deadline')
    def _check_batch_dates(self):
        for batch in self:
            if batch.date_from and batch.date_to and batch.date_from > batch.date_to:
                raise ValidationError(_("Period From must be before or equal to Period To."))
            if batch.date_deadline and batch.date_to and batch.date_deadline < batch.date_to:
                raise ValidationError(_("Appraisal Deadline must be on or after Period To."))

    def write(self, vals):
        locked_fields = {'name', 'company_id', 'date_deadline', 'date_from', 'date_to'}
        for batch in self:
            if batch.state != 'draft' and locked_fields & set(vals):
                raise UserError(_(
                    "Batch name, company, deadline, and period can only be changed in Draft state."
                ))
        res = super().write(vals)

        # Keep child appraisals synchronized with batch date controls.
        sync_vals = {}
        if 'date_deadline' in vals:
            sync_vals['appraisal_deadline'] = vals.get('date_deadline')
        if 'date_from' in vals:
            sync_vals['date_from'] = vals.get('date_from')
        if 'date_to' in vals:
            sync_vals['date_to'] = vals.get('date_to')
        if sync_vals:
            for batch in self:
                if batch.appraisal_ids:
                    batch.appraisal_ids.sudo().write(sync_vals)

        return res

    def unlink(self):
        self._check_hr_or_admin_access("delete appraisal batches")
        for batch in self:
            if batch.state != 'draft':
                raise UserError(_("Only draft appraisal batches can be deleted."))
        return super().unlink()

    def action_open_generate_wizard(self):
        self.ensure_one()
        self._check_hr_or_admin_access("generate appraisals in batch")
        if self.state != 'draft':
            raise UserError(_("Employees can only be added while the batch is in Draft state."))
        return {
            'name': _('Generate Appraisals'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.appraisal.batch.employees',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
                'default_company_id': self.company_id.id,
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def action_open_appraisals(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('oh_appraisal.hr_appraisal_action')
        action['domain'] = [('appraisal_batch_id', '=', self.id)]
        action['context'] = {'default_appraisal_batch_id': self.id}
        return action

    def action_refresh_skills_from_job(self):
        """Refresh draft appraisals in this batch from each employee's job position."""
        self._check_hr_or_admin_access("refresh appraisal skills from job position")
        refreshed = 0
        skipped = []
        for batch in self:
            draft_appraisals = batch.appraisal_ids.filtered(lambda a: a.state == 'draft')
            for appraisal in draft_appraisals:
                try:
                    if not appraisal.employee_id:
                        skipped.append(_("%s (no employee)") % appraisal.display_name)
                        continue
                    appraisal._sync_skill_lines_from_job_position()
                    refreshed += 1
                except UserError as exc:
                    name = appraisal.employee_id.name or appraisal.display_name
                    skipped.append("%s: %s" % (name, exc.args[0]))
            message = _("Refreshed skills for %s draft appraisal(s).") % refreshed
            if skipped:
                message += "<br/>" + _("Skipped:") + "<br/>- " + "<br/>- ".join(skipped)
            batch.message_post(body=message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Refresh Skills from Job'),
                'type': 'success' if refreshed else 'warning',
                'message': _("Refreshed %s appraisal(s).") % refreshed,
                'sticky': bool(skipped),
            },
        }

    def action_publish_all(self):
        self._run_bulk_state_change('action_publish', 'published', _("Published"))

    def action_submit_all(self):
        self._run_bulk_state_change('action_submit', 'submitted', _("Submitted"))

    def action_hr_finalize_all(self):
        if not self.env.user.has_group('sl_appraisal.group_appraisal_administrator') and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only Appraisal Administrators can finalize appraisal batches."))
        self._run_bulk_state_change('action_hr_finalize', 'hr_finalization', _("HR Finalized"))

    def action_reset_to_draft(self):
        self._check_hr_or_admin_access("reset appraisal batches to draft")
        self._run_bulk_state_change('action_reset_to_draft', 'draft', _("Reset to Draft"))

    def action_export_pdf(self):
        self._check_exportable()
        return self.env.ref('sl_appraisal.action_report_appraisal_batch_pdf').report_action(self)

    def action_export_xlsx(self):
        self._check_exportable()
        ids_param = ",".join(str(batch_id) for batch_id in self.ids)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/sl_appraisal/batch/export/xlsx?ids={ids_param}',
            'target': 'self',
        }

    def _run_bulk_state_change(self, method_name, target_state, label):
        for batch in self:
            batch._check_hr_or_admin_access(f"{label.lower()} appraisal batches")
            errors = []
            processed = self.env['hr.appraisal']
            for appraisal in batch.appraisal_ids:
                if target_state == 'published' and appraisal.state != 'draft':
                    continue
                if target_state == 'submitted' and appraisal.state != 'published':
                    continue
                if target_state == 'hr_finalization' and appraisal.state != 'submitted':
                    continue
                if target_state == 'draft' and appraisal.state == 'draft':
                    continue
                try:
                    appraisal_to_process = appraisal.with_context(
                        batch_force_submit=target_state == 'submitted'
                    )
                    getattr(appraisal_to_process, method_name)()
                    processed |= appraisal
                except (UserError, AccessError, ValidationError) as exc:
                    errors.append(_("%s: %s") % (appraisal.employee_id.name or appraisal.display_name, exc))

            batch._sync_state_from_appraisals(force=target_state == 'draft')

            message = _("%s %s appraisal(s).") % (label, len(processed))
            if errors:
                message += "<br/>" + _("Skipped records:") + "<br/>- " + "<br/>- ".join(errors)
            batch.message_post(body=message)

            if errors:
                raise UserError(_(
                    "Some appraisals could not be processed:\n%s"
                ) % "\n".join(errors))

    def _sync_state_from_appraisals(self, force=False):
        for batch in self:
            if not batch.appraisal_ids:
                batch.state = 'draft'
                continue
            states = set(batch.appraisal_ids.mapped('state'))
            if states == {'hr_finalization'}:
                batch.state = 'hr_finalization'
            elif not states.intersection({'draft', 'published'}) and states.intersection({'submitted', 'hr_finalization'}):
                batch.state = 'submitted'
            elif 'draft' not in states and states.intersection({'published', 'submitted', 'hr_finalization'}):
                batch.state = 'published'
            else:
                batch.state = 'draft'

    def _check_exportable(self):
        allowed_states = {'submitted', 'hr_finalization'}
        invalid = self.filtered(lambda batch: batch.state not in allowed_states)
        if invalid:
            raise UserError(_(
                "Export is only available for batches in Submitted or HR Finalization state."
            ))

    def _check_hr_or_admin_access(self, action_name):
        if not (
            self.env.user.has_group('sl_appraisal.group_appraisal_hr')
            or self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_("Only HR Officers and Administrators can %s.", action_name))
