from collections import defaultdict
from datetime import datetime, time

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
    copied_from_batch_id = fields.Many2one(
        'hr.appraisal.batch',
        string='Copied From',
        readonly=True,
        copy=False,
        index=True,
        help="Source batch this one was copied from. Only the settings were "
             "copied; when employees are generated here, the evaluator "
             "(manager / employee) assigned to them in the source batch is "
             "reused.",
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

    def _assert_can_generate_appraisals(self):
        """Allow adding employees while the batch is Draft, Published, or Submitted."""
        self.ensure_one()
        if self.state == 'hr_finalization':
            raise UserError(_(
                "Employees cannot be added while the batch is in HR Finalization."
            ))
        if self.state not in ('draft', 'published', 'submitted'):
            raise UserError(_(
                "Employees can only be added while the batch is in Draft, "
                "Published, or Submitted state."
            ))

    def action_open_generate_wizard(self):
        self.ensure_one()
        self._check_hr_or_admin_access("generate appraisals in batch")
        self._assert_can_generate_appraisals()
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

    # ── Period issues (job change / contract boundary / no contract) ──
    def _review_scope_employees(self):
        """Employees the generate wizard should consider for this batch:
        eligible, in the batch's company (or none), not yet in the batch —
        active ones, plus departed (archived) ones who still held a contract
        during the period. Ex-employees who left before the period are not
        scanned, otherwise every past employee would be flagged as
        'no contract'."""
        self.ensure_one()
        Employee = self.env['hr.employee']
        base = [
            ('appraisal_eligible', '=', True),
            ('company_id', 'in', [self.company_id.id, False]),
        ]
        active = Employee.search(base)
        contract_emp_ids = self.env['hr.contract'].sudo().with_context(
            active_test=False,
        ).search([
            ('state', 'in', ('open', 'close')),
            ('date_start', '<=', self.date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', self.date_from),
        ]).mapped('employee_id').ids
        departed = Employee.with_context(active_test=False).search(
            base + [('active', '=', False), ('id', 'in', contract_emp_ids)])
        return (active | departed) - self.appraisal_ids.mapped('employee_id')

    def _employee_period_issues(self, employees):
        """Detect, for each employee, what needs HR review before an appraisal
        is generated for this batch's period:

        - ``jobs``: hr.job recordset held during the period, in order. More
          than one means the employee changed job position in the period and
          HR must pick which position the appraisal is for. Sources: the
          employee card's job history (mail tracking on hr.employee.job_id)
          plus the job of every contract overlapping the period.
        - ``contract_boundary``: a contract starts or ends inside the period.
        - ``no_contract``: no running/closed contract overlaps the period.

        Returns ``{employee_id: {'jobs', 'job_changes', 'contract_boundary',
        'no_contract', 'summary'}}`` — only for employees with at least one
        issue. ``job_changes`` is ``[(date, old_job, new_job)]``.
        """
        self.ensure_one()
        date_from, date_to = self.date_from, self.date_to
        if not employees or not date_from or not date_to:
            return {}
        Job = self.env['hr.job'].sudo()
        Contract = self.env['hr.contract'].sudo().with_context(active_test=False)

        contracts_by_emp = defaultdict(lambda: Contract.browse())
        for contract in Contract.search([
            ('employee_id', 'in', employees.ids),
            ('state', 'in', ('open', 'close')),
            ('date_start', '<=', date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', date_from),
        ]):
            contracts_by_emp[contract.employee_id.id] |= contract

        # Job history: every change since the period started, so the job at
        # the END of the period is known even if it changed again later.
        job_field = self.env['ir.model.fields']._get('hr.employee', 'job_id')
        changes_by_emp = defaultdict(list)
        trackings = self.env['mail.tracking.value'].sudo().search([
            ('field_id', '=', job_field.id),
            ('mail_message_id.model', '=', 'hr.employee'),
            ('mail_message_id.res_id', 'in', employees.ids),
            ('mail_message_id.date', '>=', datetime.combine(date_from, time.min)),
        ])
        for tracking in trackings:
            message = tracking.mail_message_id
            changes_by_emp[message.res_id].append((
                message.date.date(),
                Job.browse(tracking.old_value_integer or 0).exists(),
                Job.browse(tracking.new_value_integer or 0).exists(),
            ))

        issues = {}
        for employee in employees:
            changes = sorted(changes_by_emp.get(employee.id, []), key=lambda c: c[0])
            in_period = [c for c in changes if c[0] <= date_to]
            after = [c for c in changes if c[0] > date_to]
            contracts = contracts_by_emp.get(employee.id, Contract.browse())
            # Ordered, de-duplicated list of job ids held in the period:
            # job at period start, then each new job, then contract jobs.
            job_ids = []
            if in_period:
                job_ids.append(in_period[0][1].id)
                job_ids.extend(new.id for _date, _old, new in in_period)
            else:
                job_ids.append((after[0][1] if after else employee.job_id).id)
            job_ids.extend(contracts.mapped('job_id').ids)
            jobs = Job.browse(list(dict.fromkeys(j for j in job_ids if j))).exists()

            boundary = contracts.filtered(
                lambda c: c.date_start > date_from
                or (c.date_end and c.date_end < date_to))
            job_change = len(jobs) > 1
            no_contract = not contracts
            if not (job_change or boundary or no_contract):
                continue

            summary = []
            if job_change:
                parts = [jobs[0].name]
                for change_date, _old, new in in_period:
                    parts.append("%s (%s)" % (new.name or "?", change_date))
                if not in_period:
                    parts = jobs.mapped('name')
                summary.append(_("Job changed: %s") % " → ".join(parts))
            for contract in boundary:
                if contract.date_start > date_from:
                    summary.append(_("Contract starts %s") % contract.date_start)
                if contract.date_end and contract.date_end < date_to:
                    summary.append(_("Contract ends %s") % contract.date_end)
            if no_contract:
                summary.append(_("No active contract in the period"))

            issues[employee.id] = {
                'jobs': jobs,
                'job_changes': in_period,
                'contract_boundary': bool(boundary),
                'no_contract': no_contract,
                'summary': "; ".join(summary),
            }
        return issues

    def _open_review_wizard(self, flagged_employees, ok_employees=None):
        """Open the review wizard for employees with period issues.
        ``ok_employees`` (no issues) are carried along and generated when the
        wizard is confirmed."""
        self.ensure_one()
        Review = self.env['hr.appraisal.batch.review']
        wizard = Review.create({
            'batch_id': self.id,
            'ok_employee_ids': [(6, 0, (ok_employees or self.env['hr.employee']).ids)],
            'line_ids': Review._prepare_line_commands(self, flagged_employees),
        })
        return {
            'name': _('Employees Needing Review'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.appraisal.batch.review',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _generate_appraisals_for_employees(self, employees, job_by_employee=None):
        """Create one appraisal per employee in this batch, mirroring the
        batch period/deadline. Shared by the generate wizard and the review
        wizard so both paths behave identically.

        Evaluator: when this batch was copied from another one, the
        manager/employee assigned to the employee in the source batch is
        reused; otherwise the employee's direct manager.

        ``job_by_employee`` ({employee_id: job_id}) pins the appraisal's Job
        Position for employees who changed job during the period.

        New appraisals stay Draft when the batch is Draft. When the batch is
        Published or Submitted they are auto-published so the batch status
        stays coherent.
        """
        self.ensure_one()
        self._assert_can_generate_appraisals()
        ineligible = employees.filtered(lambda e: not e.appraisal_eligible)
        if ineligible:
            raise UserError(_(
                "These employees are not eligible for appraisals (the "
                "'Appraisal' box is unchecked on their employee card):\n%s"
            ) % "\n".join(ineligible.mapped('name')))
        job_by_employee = job_by_employee or {}
        source_by_employee = {}
        if self.copied_from_batch_id:
            for src in self.copied_from_batch_id.sudo().appraisal_ids:
                source_by_employee.setdefault(src.employee_id.id, src)
        appraisal_model = self.env['hr.appraisal'].sudo()
        auto_publish = self.state in ('published', 'submitted')
        created = self.env['hr.appraisal']
        for employee in employees:
            vals = {
                'employee_id': employee.id,
                'company_id': employee.company_id.id or self.company_id.id,
                'appraisal_deadline': self.date_deadline,
                'date_from': self.date_from,
                'date_to': self.date_to,
                'appraisal_batch_id': self.id,
            }
            if job_by_employee.get(employee.id):
                vals['job_id'] = job_by_employee[employee.id]
            source = source_by_employee.get(employee.id)
            source_managers = source.hr_manager_ids.filtered('active') if source else None
            source_employees = source.hr_employee_ids.filtered('active') if source else None
            if source_managers or source_employees:
                vals['hr_manager_ids'] = [(6, 0, source_managers.ids)]
                vals['hr_employee_ids'] = [(6, 0, source_employees.ids)]
            elif employee.parent_id.user_id:
                vals['hr_manager_ids'] = [(6, 0, employee.parent_id.ids)]
            appraisal = appraisal_model.create(vals)
            if employee.employee_skill_ids and not appraisal.skills_populated:
                appraisal.action_populate_skills()
            created |= appraisal

        if auto_publish:
            previous_state = self.state
            for appraisal in created:
                try:
                    appraisal.action_publish()
                except (UserError, AccessError, ValidationError) as exc:
                    raise UserError(_(
                        "Could not auto-publish appraisal for %(employee)s: %(error)s"
                    ) % {
                        'employee': appraisal.employee_id.name or appraisal.display_name,
                        'error': exc.args[0] if exc.args else str(exc),
                    }) from exc
            # Keep the batch in Published/Submitted. Sync would demote a
            # Submitted batch to Published when late appraisals are still open.
            if self.state != previous_state:
                self.state = previous_state

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
        """Copy selected batch(es): a fresh draft batch per source with the
        same settings and a link to the source. NO appraisals are created —
        employees are added through Generate Appraisals, so job/contract
        issues are reviewed for the new period, and each employee's evaluator
        (manager or employee) is taken from the source batch."""
        self._check_hr_or_admin_access("duplicate appraisal batches")
        new_batches = self.env['hr.appraisal.batch']
        for batch in self:
            new_batch = self.env['hr.appraisal.batch'].create({
                'name': _("%s (copy)", batch.name),
                'company_id': batch.company_id.id,
                'date_deadline': batch.date_deadline,
                'date_from': batch.date_from,
                'date_to': batch.date_to,
                'copied_from_batch_id': batch.id,
            })
            new_batch.message_post(body=_(
                "Copied from batch %(name)s: settings and the evaluator "
                "assignment of %(count)s employee(s). No appraisals were "
                "created — use Generate Appraisals to add employees; the "
                "manager/employee who appraised them in the source batch "
                "will be assigned automatically.",
                name=batch.name, count=len(batch.appraisal_ids),
            ))
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
