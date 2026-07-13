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
    submitted_appraisal_count = fields.Integer(
        string='Submitted Appraisals',
        compute='_compute_submitted_appraisal_count',
    )
    is_appraisal_admin = fields.Boolean(
        compute='_compute_is_appraisal_admin',
    )

    @api.depends('appraisal_ids')
    def _compute_appraisal_count(self):
        for batch in self:
            batch.appraisal_count = len(batch.appraisal_ids)

    @api.depends('appraisal_ids', 'appraisal_ids.state')
    def _compute_submitted_appraisal_count(self):
        for batch in self:
            batch.submitted_appraisal_count = len(
                batch.appraisal_ids.filtered(lambda a: a.state == 'submitted')
            )

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
        locked_when_not_draft = {'name', 'company_id'}
        for batch in self:
            if batch.state != 'draft' and locked_when_not_draft & set(vals):
                raise UserError(_(
                    "Batch name and company can only be changed in Draft state."
                ))
        res = super().write(vals)

        sync_fields = {'date_deadline', 'date_from', 'date_to'}
        if sync_fields & set(vals):
            for batch in self:
                if not batch.appraisal_ids:
                    continue
                sync_vals = {}
                if 'date_deadline' in vals:
                    sync_vals['appraisal_deadline'] = batch.date_deadline
                if 'date_from' in vals:
                    sync_vals['date_from'] = batch.date_from
                if 'date_to' in vals:
                    sync_vals['date_to'] = batch.date_to
                if sync_vals:
                    batch.appraisal_ids.with_context(
                        appraisal_batch_sync=True,
                    ).sudo().write(sync_vals)

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

    def _generate_appraisals_for_employees(self, employees):
        """Create one draft appraisal per employee in this batch, mirroring
        the batch period/deadline and defaulting the evaluator to the
        employee's direct manager. Shared by the generate wizard and the
        contract-warning wizard so both paths behave identically."""
        self.ensure_one()
        appraisal_model = self.env['hr.appraisal'].sudo()
        for employee in employees:
            vals = {
                'employee_id': employee.id,
                'company_id': employee.company_id.id or self.company_id.id,
                'appraisal_deadline': self.date_deadline,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'appraisal_batch_id': self.id,
            }
            if employee.parent_id.user_id:
                vals['hr_manager_ids'] = [(6, 0, employee.parent_id.ids)]
            appraisal = appraisal_model.create(vals)
            if employee.employee_skill_ids and not appraisal.skills_populated:
                appraisal.action_populate_skills()
        self.message_post(
            body=_("Generated %s appraisal(s) from the batch wizard.") % len(employees)
        )

    def action_open_appraisals(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('oh_appraisal.hr_appraisal_action')
        action['domain'] = [('appraisal_batch_id', '=', self.id)]
        action['context'] = {'default_appraisal_batch_id': self.id}
        return action

    def action_refresh_skills_from_job(self):
        """Refresh draft appraisals in this batch from each employee card."""
        self._check_hr_or_admin_access("refresh appraisal skills from employee card")
        refreshed = 0
        skipped = []
        for batch in self:
            draft_appraisals = batch.appraisal_ids.filtered(lambda a: a.state == 'draft')
            for appraisal in draft_appraisals:
                try:
                    if not appraisal.employee_id:
                        skipped.append(_("%s (no employee)") % appraisal.display_name)
                        continue
                    appraisal._sync_skill_lines_from_employee()
                    refreshed += 1
                except UserError as exc:
                    name = appraisal.employee_id.name or appraisal.display_name
                    skipped.append("%s: %s" % (name, exc.args[0]))
            message = _("Refreshed skills from employee card for %s draft appraisal(s).") % refreshed
            if skipped:
                message += "<br/>" + _("Skipped:") + "<br/>- " + "<br/>- ".join(skipped)
            batch.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_publish_all(self):
        self._run_bulk_state_change('action_publish', 'published', _("Published"))

    def action_submit_all(self):
        self._run_bulk_state_change('action_submit', 'submitted', _("Submitted"))

    def action_sync_hr_scores_from_manager(self):
        """Sync HR skill scores from manager feedback for submitted appraisals in the batch."""
        self._check_hr_or_admin_access("sync HR skill scores from manager feedback")
        synced_total = 0
        for batch in self:
            appraisals = batch.appraisal_ids.filtered(lambda a: a.state == 'submitted')
            if appraisals:
                appraisals._sync_skill_lines_hr_from_manager_feedback()
                synced_total += len(appraisals)
                batch.message_post(body=_(
                    "Synced HR skill scores from manager feedback for %(count)s submitted appraisal(s).",
                    count=len(appraisals),
                ))
            else:
                batch.message_post(body=_(
                    "No appraisals in Submitted state to sync in this batch."
                ))
        if not synced_total:
            raise UserError(_("No appraisals in Submitted state were found in the selected batch(es)."))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_hr_finalize_all(self):
        if not self.env.user.has_group('sl_appraisal.group_appraisal_administrator') and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only Appraisal Administrators can finalize appraisal batches."))
        self._run_bulk_state_change('action_hr_finalize', 'hr_finalization', _("HR Finalized"))

    def action_reset_to_draft(self):
        self._check_hr_or_admin_access("reset appraisal batches to draft")
        self._run_bulk_state_change('action_reset_to_draft', 'draft', _("Reset to Draft"))

    def action_duplicate_batch(self):
        """Duplicate selected batch(es): a fresh draft batch per source, with one
        draft appraisal per employee carrying the same manager assignment and
        freshly populated skills."""
        self._check_hr_or_admin_access("duplicate appraisal batches")
        appraisal_model = self.env['hr.appraisal']
        new_batches = self.env['hr.appraisal.batch']
        for batch in self:
            new_batch = self.env['hr.appraisal.batch'].create({
                'name': _("%s (copy)", batch.name),
                'company_id': batch.company_id.id,
                'date_deadline': batch.date_deadline,
                'date_from': batch.date_from,
                'date_to': batch.date_to,
            })
            for appraisal in batch.appraisal_ids:
                vals = {
                    'employee_id': appraisal.employee_id.id,
                    'company_id': appraisal.company_id.id or new_batch.company_id.id,
                    'appraisal_deadline': new_batch.date_deadline,
                    'date_from': new_batch.date_from,
                    'date_to': new_batch.date_to,
                    'appraisal_batch_id': new_batch.id,
                    # preserve the exact evaluator assignment (manager or employee)
                    'hr_manager_ids': [(6, 0, appraisal.hr_manager_ids.ids)],
                    'hr_employee_ids': [(6, 0, appraisal.hr_employee_ids.ids)],
                }
                # appraisal_batch_sync=True skips the past-deadline constraint so an
                # old batch can still be duplicated (same trick the batch date-sync uses)
                new_appraisal = appraisal_model.with_context(
                    appraisal_batch_sync=True,
                ).create(vals)
                if new_appraisal.employee_id.employee_skill_ids and not new_appraisal.skills_populated:
                    new_appraisal.action_populate_skills()
            new_batch.message_post(
                body=_("Duplicated from batch %s with %s appraisal(s).",
                       batch.name, len(batch.appraisal_ids)))
            new_batches |= new_batch

        action = self.env['ir.actions.actions']._for_xml_id(
            'sl_appraisal.action_hr_appraisal_batch')
        if len(new_batches) == 1:
            action['res_id'] = new_batches.id
            action['view_mode'] = 'form'
            action['views'] = [
                (self.env.ref('sl_appraisal.view_hr_appraisal_batch_form').id, 'form')]
        else:
            action['domain'] = [('id', 'in', new_batches.ids)]
        return action

    def action_export_pdf(self):
        return self.env.ref('sl_appraisal.action_report_appraisal_batch_pdf').report_action(self)

    def action_export_xlsx(self):
        ids_param = ",".join(str(batch_id) for batch_id in self.ids)
        # Forward the currently selected companies so the export honours the
        # same multi-company scope as the appraisal list view.
        cids_param = ",".join(str(cid) for cid in self.env.companies.ids)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/sl_appraisal/batch/export/xlsx?ids={ids_param}&cids={cids_param}',
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

    def _check_hr_or_admin_access(self, action_name):
        if not (
            self.env.user.has_group('sl_appraisal.group_appraisal_hr')
            or self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_("Only HR Officers and Administrators can %s.", action_name))
