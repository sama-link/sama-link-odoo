from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, AccessError, ValidationError


class HrAppraisal(models.Model):
    _inherit = 'hr.appraisal'

    # ── State field (replaces old Kanban stages) ──────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('submitted', 'Submitted'),
        ('hr_finalization', 'HR Finalization'),
    ], string='Status', default='draft', tracking=True, copy=False,
        help="Draft: HR prepares appraisal.\n"
             "Published: Feedback in progress.\n"
             "Submitted: Feedback locked for manager review.\n"
             "HR Finalization: HR reviews and approves skill changes.")

    date_from = fields.Date(string='Period From')
    date_to = fields.Date(string='Period To')

    # ── Skills evaluation lines ───────────────────────────────────────
    appraisal_skill_line_ids = fields.One2many(
        'appraisal.skill.line', 'appraisal_id',
        string='Skills Evaluation',
        help="Skills evaluated during this appraisal cycle")

    skills_populated = fields.Boolean(
        string='Skills Populated', default=False, copy=False,
        help="Technical flag: skills have been auto-populated from employee")

    # ── Computed / display helpers ────────────────────────────────────
    skill_line_count = fields.Integer(
        string='Skills Count', compute='_compute_skill_line_count')

    is_hr_or_admin = fields.Boolean(
        string='Is HR/Admin', compute='_compute_is_hr_or_admin')
    is_appraisal_admin = fields.Boolean(
        string='Is Appraisal Admin',
        compute='_compute_is_appraisal_admin')
    is_in_access_plan = fields.Boolean(
        string='In Access Plan',
        compute='_compute_is_in_access_plan')

    allowed_manager_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_allowed_manager_ids',
        compute_sudo=True,
        string='Allowed Evaluators',
        help="Employees that can be selected as manager evaluators.")

    hr_employee_ids = fields.Many2many(
        'hr.employee',
        'employee_appraisal_rel',
        'appraisal_id',
        'employee_id',
        string='Select Employees',
        help="Employees who can access this appraisal.")

    access_user_ids = fields.Many2many(
        'res.users',
        compute='_compute_access_user_ids',
        compute_sudo=True,
        store=True,
        string='Allowed Access Users',
        help="Users allowed to access this appraisal as evaluator/manager/coach.")

    manager_feedback_ids = fields.One2many(
        'appraisal.skill.manager.feedback', 'appraisal_id',
        string='Manager Feedback')

    skill_average_score = fields.Float(
        string='Skills Average (%)',
        compute='_compute_scores',
        store=True,
        digits=(16, 2),
        help="Average percentage of all skills in this appraisal.")

    manual_score = fields.Float(
        string='Manual Score (%)',
        digits=(16, 2),
        help="Additional score entered by HR (0 to 15).")

    final_hr_score = fields.Float(
        string='Final HR Score (%)',
        digits=(16, 2),
        help="Final score set by Appraisal Administrator and used in total score.")

    manual_score_display = fields.Float(
        string='Score Tab Value (%)',
        compute='_compute_manual_score_display',
        readonly=True,
        help="Displays the score entered in the Score tab before finalization, and final HR score after.")

    total_score = fields.Float(
        string='Total Score (%)',
        compute='_compute_scores',
        store=True,
        digits=(16, 2),
        help="Sum of Skills Average and Manual Score.")

    manual_score_reason = fields.Text(
        string='Score Reason',
        help="Reason for the manual score adjustment.")

    final_reason = fields.Text(
        string='Final Reason',
        help="Optional reason provided by Administrator for the final score.")

    # ─── Overrides ────────────────────────────────────────────────────

    @api.depends('appraisal_skill_line_ids')
    def _compute_skill_line_count(self):
        for rec in self:
            rec.skill_line_count = len(rec.appraisal_skill_line_ids)

    @api.depends(
        'appraisal_skill_line_ids',
        'appraisal_skill_line_ids.computed_current_level_progress',
        'appraisal_skill_line_ids.final_level_progress',
        'final_hr_score',
    )
    def _compute_scores(self):
        for rec in self:
            percentages = []
            for line in rec.appraisal_skill_line_ids:
                # Prefer final approved level; fallback to current level.
                value = line.final_level_progress or line.computed_current_level_progress or 0
                percentages.append(value)
            rec.skill_average_score = sum(percentages) / len(percentages) if percentages else 0.0
            rec.total_score = rec.skill_average_score + (rec.final_hr_score or 0.0)

    @api.depends('manual_score', 'final_hr_score', 'state')
    def _compute_manual_score_display(self):
        for rec in self:
            if rec.state == 'hr_finalization':
                rec.manual_score_display = rec.final_hr_score or 0.0
            else:
                rec.manual_score_display = rec.manual_score or 0.0

    @api.depends_context('uid')
    def _compute_is_hr_or_admin(self):
        is_hr = self.env.user.has_group(
            'sl_appraisal.group_appraisal_hr')
        is_admin = self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
        for rec in self:
            rec.is_hr_or_admin = is_hr or is_admin

    @api.depends_context('uid')
    def _compute_is_appraisal_admin(self):
        is_admin = (
            self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        )
        for rec in self:
            rec.is_appraisal_admin = is_admin

    @api.depends_context('uid')
    @api.depends('access_user_ids')
    def _compute_is_in_access_plan(self):
        for rec in self:
            rec.is_in_access_plan = self.env.user in rec.access_user_ids

    @api.depends('employee_id', 'employee_id.parent_id', 'employee_id.coach_id')
    def _compute_allowed_manager_ids(self):
        for rec in self:
            managers = self.env['hr.employee']
            if rec.employee_id:
                managers |= rec.employee_id.parent_id
                managers |= rec.employee_id.coach_id
            rec.allowed_manager_ids = managers.filtered(lambda e: e.user_id)

    @api.depends(
        'employee_id', 'employee_id.user_id', 'employee_id.parent_id.user_id',
        'employee_id.coach_id.user_id', 'hr_manager_ids.user_id',
        'hr_employee_ids.user_id', 'creater_id'
    )
    def _compute_access_user_ids(self):
        for rec in self:
            users = self.env['res.users']
            if rec.employee_id and rec.employee_id.user_id:
                users |= rec.employee_id.user_id
            users |= rec._get_selected_access_employees().mapped('user_id')
            # Always include creator for traceability access.
            if rec.creater_id:
                users |= rec.creater_id
            rec.access_user_ids = users

    def _get_selected_access_employees(self):
        self.ensure_one()
        return (
            self.hr_manager_ids
            | self.hr_employee_ids
        ).filtered(lambda emp: emp.user_id)

    @api.constrains('hr_manager_ids', 'hr_employee_ids')
    def _check_single_access_person(self):
        for rec in self:
            selected_employees = rec._get_selected_access_employees()
            if len(selected_employees) > 1:
                raise ValidationError(_(
                    "Only one person can be selected to access the appraisal form."
                ))

    @api.constrains('manual_score', 'manual_score_reason', 'final_hr_score', 'total_score')
    def _check_score_limits(self):
        for rec in self:
            if rec.manual_score < 0 or rec.manual_score > 15:
                raise ValidationError(_("Manual score must be between 0 and 15."))
            if rec.final_hr_score < 0 or rec.final_hr_score > 15:
                raise ValidationError(_("Final HR score must be between 0 and 15."))
            if rec.manual_score and not rec.manual_score_reason:
                raise ValidationError(_("Score reason is mandatory when manual score is set."))
            if rec.total_score > 100:
                raise ValidationError(_("Total score cannot exceed 100%%."))

    @api.onchange('manual_score')
    def _onchange_manual_score(self):
        for rec in self:
            if rec.manual_score < 0:
                rec.manual_score = 0
            if rec.manual_score > 15:
                rec.manual_score = 15
            max_by_total = max(0.0, 100.0 - (rec.skill_average_score or 0.0))
            if rec.manual_score > max_by_total:
                rec.manual_score = max_by_total
                return {
                    'warning': {
                        'title': _("Score adjusted"),
                        'message': _(
                            "Manual score was reduced so the total does not exceed 100%%."
                        ),
                    }
                }

    # ─── CRUD restrictions ────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Only HR Officers and Administrators can create appraisals."""
        self._check_hr_or_admin_access("create appraisals")
        vals['state'] = 'draft'
        record = super().create(vals)
        return record

    def write(self, vals):
        """Restrict writes by role and appraisal access plan."""
        is_admin = self.env.user.has_group('sl_appraisal.group_appraisal_administrator') or self.env.user.has_group('base.group_system')
        is_hr_officer = self.env.user.has_group('sl_appraisal.group_appraisal_hr')
        is_manager = self.env.user.has_group('sl_appraisal.group_appraisal_manager') or is_hr_officer



        if is_hr_officer and not is_admin:
            for rec in self:
                # HR Officer can prepare draft and publish even if not selected.
                if rec.state == 'draft':
                    continue
                allowed_users = rec._get_selected_access_employees().mapped('user_id')
                if self.env.user not in allowed_users:
                    # Allow only publish transition while still in draft; all
                    # other edits require being selected in access plan.
                    if vals.get('state') == 'published' and set(vals) == {'state'}:
                        continue
                    raise AccessError(_("You can edit this appraisal only if you are selected in the Access Plan."))

        if is_manager or is_admin:
            for rec in self:
                # Admin needs access plan for manager-specific fields
                # but can always edit admin-only fields.
                if is_admin:
                    manager_fields = {'manual_score', 'manual_score_reason'}
                    editing_manager_fields = manager_fields & set(vals)
                    if editing_manager_fields and rec.state != 'draft':
                        allowed_users = rec._get_selected_access_employees().mapped('user_id')
                        if self.env.user not in allowed_users:
                            raise AccessError(_(
                                "You must be selected in the Access Plan to edit manager fields."
                            ))
                    continue

                # In non-draft states, users must be selected in access plan.
                if rec.state != 'draft':
                    allowed_users = rec._get_selected_access_employees().mapped('user_id')
                    if self.env.user not in allowed_users:
                        raise AccessError(_("You can edit this appraisal only if you are selected in the Access Plan."))

                if 'state' in vals:
                    next_state = vals.get('state')
                    if next_state == 'submitted':
                        if rec.state != 'published':
                            raise AccessError(_("Only published appraisals can be submitted."))
                        allowed_users = rec._get_selected_access_employees().mapped('user_id')
                        if self.env.user not in allowed_users:
                            raise AccessError(_("Only selected manager/employee can submit."))
                    elif next_state == 'published' and is_hr_officer and rec.state == 'draft':
                        # HR publish allowed.
                        pass
                    else:
                        raise AccessError(_("You cannot change appraisal state in this operation."))

                # Manager/HR can only edit in Published or Draft state.
                # Field-level access is already enforced by view readonly attrs.
                non_state_fields = set(vals) - {'state'}
                if non_state_fields:
                    if rec.state == 'draft' and is_hr_officer:
                        continue
                    if rec.state != 'published':
                        raise AccessError(_("Appraisal can only be edited while in Published state."))

        if 'state' in vals and not self._is_hr_or_admin():
            # Allow assigned users/managers to submit Published -> Submitted.
            requested_state = vals.get('state')
            if requested_state == 'submitted':
                for rec in self:
                    allowed_users = rec._get_selected_access_employees().mapped('user_id')
                    if rec.state != 'published' or self.env.user not in allowed_users:
                        raise AccessError(
                            _("Only assigned users can submit a published appraisal.")
                        )
            else:
                raise AccessError(
                    _("Only HR Officers and Administrators can change "
                      "the appraisal status."))
        return super().write(vals)

    def unlink(self):
        """Only allow deletion by HR/Admin and only in draft state."""
        self._check_hr_or_admin_access("delete appraisals")
        for rec in self:
            if rec.state != 'draft':
                raise UserError(
                    _("You can only delete appraisals in Draft state."))
        return super().unlink()

    # ─── Workflow buttons ─────────────────────────────────────────────

    def action_populate_skills(self):
        """Populate skills evaluation lines from employee's current skills."""
        self.ensure_one()
        if self.skills_populated:
            raise UserError(
                _("Skills have already been populated for this appraisal."))
        if not self.employee_id:
            raise UserError(_("Please select an employee first."))
        commands = []
        for emp_skill in self.employee_id.employee_skill_ids:
            commands.append(Command.create({
                'skill_type_id': emp_skill.skill_type_id.id,
                'skill_id': emp_skill.skill_id.id,
                'current_skill_level_id': emp_skill.skill_level_id.id,
            }))
        self.write({
            'appraisal_skill_line_ids': commands,
            'skills_populated': True,
        })

    def action_publish(self):
        """Move appraisal from Draft → Published."""
        self.ensure_one()
        self._check_hr_or_admin_access("publish appraisals")
        if self.state != 'draft':
            raise UserError(_("Only draft appraisals can be published."))
        if self.employee_id and self.hr_manager_ids:
            invalid = self.hr_manager_ids - self.allowed_manager_ids
            if invalid:
                raise UserError(_(
                    "Only the employee's direct manager/coach can be selected as manager evaluators."
                ))
        selected_employees = self._get_selected_access_employees()
        if not selected_employees:
            raise UserError(
                _("Please select one person who can access this appraisal form before publishing.")
            )
        if len(selected_employees) > 1:
            raise UserError(_("Only one person can access this appraisal form."))
        
        self.write({'state': 'published'})
        
        # Ping the selected evaluator in the chatter
        assigned_user = selected_employees.user_id
        if assigned_user and assigned_user.partner_id:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            # Get the correct action ID so Odoo mounts the custom appraisal view
            action = self.env.ref('oh_appraisal.hr_appraisal_action', raise_if_not_found=False)
            action_id = action.id if action else ''
            
            # Construct the exact URL bypassing any default survey routing
            appraisal_url = f"{base_url}/web#id={self.id}&action={action_id}&model=hr.appraisal&view_type=form"
            
            body = _("Hello %s, this appraisal is now published and ready for your feedback. You can access the appraisal form directly here: %s") % (
                assigned_user.partner_id.name, appraisal_url
            )
            self.message_post(
                body=body,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                partner_ids=[assigned_user.partner_id.id]
            )

    def action_submit(self):
        """Move appraisal from Published -> Submitted.
        Allowed for selected manager/user only."""
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_("Only published appraisals can be submitted."))


        is_selected_user = self.env.user in self._get_selected_access_employees().mapped('user_id')
        if not is_selected_user:
            raise AccessError(_("Only selected manager/employee can submit."))

        # Snapshot final HR score from manual score at submit time.
        # Use sudo() for these internal bookkeeping writes because the
        # manager-restriction guard in write() does not whitelist
        # final_hr_score / hr_skill_score_level_id.  Access was already
        # validated above, so escalating here is safe.
        self.sudo().final_hr_score = self.manual_score or 0.0

        # On submit, initialize HR score from manager feedback score once.
        for line in self.sudo().appraisal_skill_line_ids:
            if not line.hr_skill_score_level_id and line.manager_feedback_skill_level_id:
                line.hr_skill_score_level_id = line.manager_feedback_skill_level_id

        self.write({'state': 'submitted'})

    def action_hr_finalize(self):
        """Move appraisal from Published → HR Finalization.
        Auto-update employee skills with approved levels."""
        self.ensure_one()
        if not (
            self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError(_("Only Appraisal Administrators can finalize appraisals."))
        if self.state != 'submitted':
            raise UserError(
                _("Only submitted appraisals can be finalized."))
        self._apply_hr_scores_to_final_levels()
        self.write({'state': 'hr_finalization'})
        # Auto-update employee skills
        self._update_employee_skills()
        self._create_skill_timeline()

    def action_reset_to_draft(self):
        """Reset appraisal back to Draft state."""
        self.ensure_one()
        self._check_hr_or_admin_access("reset appraisals to draft")
        self.write({
            'state': 'draft',
            'check_sent': False,
            'check_draft': True,
            'check_done': False,
            'check_cancel': False,
        })

    @api.model
    def _cron_auto_submit_appraisals(self):
        """Auto-submit published appraisals whose deadline has reached or passed."""
        today = fields.Date.today()
        # Auto submit relying on appraisal_deadline bounds
        appraisals = self.search([
            ('state', '=', 'published'),
            ('appraisal_deadline', '<=', today)
        ])
        for appraisal in appraisals:
            for line in appraisal.appraisal_skill_line_ids:
                if not line.hr_skill_score_level_id and line.manager_feedback_skill_level_id:
                    line.hr_skill_score_level_id = line.manager_feedback_skill_level_id
            
            appraisal.write({'state': 'submitted'})
            appraisal.message_post(
                body=_("Appraisal auto-submitted because the deadline has elapsed."),
                subtype_xmlid='mail.mt_note',
            )

    # ─── Internal helpers ─────────────────────────────────────────────

    def _is_hr_or_admin(self):
        return (self.env.user.has_group(
            'sl_appraisal.group_appraisal_hr')
            or self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system'))

    def _check_hr_or_admin_access(self, action_name):
        if not self._is_hr_or_admin():
            raise AccessError(
                _("Only HR Officers and Administrators can %s.",
                  action_name))

    @api.onchange('employee_id')
    def _onchange_employee_id_limit_managers(self):
        for rec in self:
            if rec.hr_manager_ids:
                rec.hr_manager_ids = rec.hr_manager_ids & rec.allowed_manager_ids

    def _apply_hr_scores_to_final_levels(self):
        for appraisal in self:
            for line in appraisal.appraisal_skill_line_ids:
                if line.hr_skill_score_level_id:
                    line.final_skill_level_id = line.hr_skill_score_level_id

    def _update_employee_skills(self):
        """Update employee skill levels based on HR-approved final levels."""
        for appraisal in self:
            employee = appraisal.employee_id
            if not employee:
                continue
            for skill_line in appraisal.appraisal_skill_line_ids:
                final_level = skill_line.final_skill_level_id
                if not final_level:
                    # HR hasn't set a final level — skip
                    continue
                # Find existing employee skill for this skill
                existing = employee.employee_skill_ids.filtered(
                    lambda s: s.skill_id.id == skill_line.skill_id.id)
                if existing:
                    existing.write({
                        'skill_level_id': final_level.id,
                    })
                else:
                    # Create new skill on employee
                    employee.write({
                        'employee_skill_ids': [Command.create({
                            'skill_type_id': skill_line.skill_type_id.id,
                            'skill_id': skill_line.skill_id.id,
                            'skill_level_id': final_level.id,
                        })]
                    })

    def _create_skill_timeline(self):
        history_model = self.env['appraisal.skill.history']
        for appraisal in self:
            for line in appraisal.appraisal_skill_line_ids.filtered(lambda l: l.final_skill_level_id):
                history_model.create({
                    'employee_id': appraisal.employee_id.id,
                    'appraisal_id': appraisal.id,
                    'date_from': appraisal.date_from,
                    'date_to': appraisal.date_to,
                    'skill_type_id': line.skill_type_id.id,
                    'skill_id': line.skill_id.id,
                    'old_level_id': line.current_skill_level_id.id,
                    'new_level_id': line.final_skill_level_id.id,
                    'change_state': line.level_change or 'same',
                })
