from datetime import datetime, time
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, AccessError, ValidationError


class HrAppraisal(models.Model):
    _inherit = 'hr.appraisal'

    appraisal_batch_id = fields.Many2one(
        'hr.appraisal.batch',
        string='Appraisal Batch',
        ondelete='set null',
        index=True,
        copy=False,
    )

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
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True,
        readonly=True,
    )
    work_location_id = fields.Many2one(
        'hr.work.location',
        string='Work Location',
        related='employee_id.work_location_id',
        store=True,
        readonly=True,
    )
    general_manager_id = fields.Many2one(
        'hr.employee',
        string='General Manager',
        related='employee_id.parent_id',
        store=True,
        readonly=True,
    )
    coach_manager_id = fields.Many2one(
        'hr.employee',
        string='Coach Manager',
        related='employee_id.coach_id',
        store=True,
        readonly=True,
    )

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
    hr_manager_id = fields.Many2one(
        'hr.employee',
        string='Select Manager',
        compute='_compute_single_access_fields',
        inverse='_inverse_hr_manager_id',
        help="Single-select proxy for manager evaluator.")
    hr_employee_id = fields.Many2one(
        'hr.employee',
        string='Select Employee',
        compute='_compute_single_access_fields',
        inverse='_inverse_hr_employee_id',
        help="Single-select proxy for employee evaluator.")

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

    absence_count = fields.Integer(
        string='Unexcused Absence Days',
        compute='_compute_administration_scores',
    )
    absence_score = fields.Float(
        string='Absence Score',
        compute='_compute_administration_scores',
        digits=(16, 2),
    )
    late_count = fields.Integer(
        string='Late Days',
        compute='_compute_administration_scores',
    )
    late_score = fields.Float(
        string='Late Score',
        compute='_compute_administration_scores',
        digits=(16, 2),
    )
    early_leaving_count = fields.Integer(
        string='Early Leaving Days',
        compute='_compute_administration_scores',
    )
    early_leaving_score = fields.Float(
        string='Early Leaving Score',
        compute='_compute_administration_scores',
        digits=(16, 2),
    )
    period_days = fields.Integer(
        string='Period Days',
        compute='_compute_administration_scores',
    )
    penalty_count = fields.Integer(
        string='Penalties',
        compute='_compute_administration_scores',
    )
    penalty_score = fields.Float(
        string='Penalty Score',
        compute='_compute_administration_scores',
        digits=(16, 2),
    )
    bonus_count = fields.Integer(
        string='Bonuses',
        compute='_compute_administration_scores',
    )
    bonus_score = fields.Float(
        string='Bonus Score',
        compute='_compute_administration_scores',
        digits=(16, 2),
    )
    admin_score = fields.Float(
        string='Administration Score (%)',
        compute='_compute_administration_scores',
        digits=(16, 2),
        help="Starts from 100 and is adjusted by absence/late/penalty/bonus scoring.",
    )
    weighted_skill_score = fields.Float(
        string='Weighted Skills + Manual (70%)',
        compute='_compute_weighted_score_breakdown',
        digits=(16, 2),
    )
    weighted_admin_score = fields.Float(
        string='Weighted Administration (30%)',
        compute='_compute_weighted_score_breakdown',
        digits=(16, 2),
    )

    total_score = fields.Float(
        string='Total Score (%)',
        compute='_compute_total_score',
        inverse='_inverse_total_score',
        store=True,
        digits=(16, 2),
        help="Sum of Skills Average and Manual Score. Editable by Appraisal Administrator only.")
    total_score_manual_override = fields.Boolean(
        string='Total Score Manual Override',
        default=False,
        copy=False,
    )

    manual_score_reason = fields.Text(
        string='Score Reason',
        help="Reason for the manual score adjustment.")

    # ─── Overrides ────────────────────────────────────────────────────

    @api.depends('appraisal_skill_line_ids')
    def _compute_skill_line_count(self):
        for rec in self:
            rec.skill_line_count = len(rec.appraisal_skill_line_ids)

    @api.depends(
        'appraisal_skill_line_ids',
        'appraisal_skill_line_ids.computed_current_level_progress',
        'appraisal_skill_line_ids.final_level_progress',
    )
    def _compute_scores(self):
        for rec in self:
            percentages = []
            for line in rec.appraisal_skill_line_ids:
                value = line.final_level_progress or line.computed_current_level_progress or 0
                percentages.append(value)
            rec.skill_average_score = sum(percentages) / len(percentages) if percentages else 0.0

    @api.depends('skill_average_score', 'manual_score')
    def _compute_weighted_score_breakdown(self):
        for rec in self:
            rec.weighted_skill_score = ((rec.skill_average_score or 0.0) + (rec.manual_score or 0.0)) * 0.7
            rec.weighted_admin_score = (rec.admin_score or 0.0) * 0.3

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_administration_scores(self):
        incentive_model = self.env['hr.incentive'].sudo()
        absence_model = self.env['hr.absent.entry'].sudo()
        attendance_model = self.env['hr.attendance'].sudo()
        config = self.env['appraisal.admin.score.config'].sudo().get_config()
        for rec in self:
            rec.absence_count = 0
            rec.late_count = 0
            rec.early_leaving_count = 0
            rec.period_days = 0
            rec.penalty_count = 0
            rec.bonus_count = 0
            rec.absence_score = 0.0
            rec.late_score = 0.0
            rec.early_leaving_score = 0.0
            rec.penalty_score = 0.0
            rec.bonus_score = 0.0
            rec.admin_score = 100.0
            if not rec.employee_id or not rec.date_from or not rec.date_to:
                continue

            rec.period_days = (rec.date_to - rec.date_from).days + 1
            date_from_midnight = datetime.combine(rec.date_from, time.min)
            date_to_end = datetime.combine(rec.date_to, time.max)

            # Match payroll / samalink_hr: absence entries are generated only for real absences.
            rec.absence_count = absence_model.search_count([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', rec.date_from),
                ('date', '<=', rec.date_to),
            ])

            attendances = attendance_model.search([
                ('employee_id', '=', rec.employee_id.id),
                ('check_in', '>=', date_from_midnight),
                ('check_in', '<=', date_to_end),
            ])
            late_data = attendances.filtered(
                'late_check_in_approved'
            ).get_late_days_hours()
            rec.late_count = late_data['late_days']

            early_data = attendances.filtered(
                'early_check_out_approved'
            ).get_early_leaving_days_hours()
            rec.early_leaving_count = early_data['early_leaving_days']

            rec.penalty_count = incentive_model.search_count([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', rec.date_from),
                ('date', '<=', rec.date_to),
                ('state', '=', 'approved'),
                ('payment_type', '=', 'with_salary'),
                ('type', '=', 'penalty'),
            ])
            rec.bonus_count = incentive_model.search_count([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', rec.date_from),
                ('date', '<=', rec.date_to),
                ('state', '=', 'approved'),
                ('payment_type', '=', 'with_salary'),
                ('type', '=', 'bonus'),
            ])
            rec.absence_score = rec.absence_count * (config.absence_points or 0.0)
            rec.late_score = rec.late_count * (config.late_points or 0.0)
            rec.early_leaving_score = rec.early_leaving_count * (config.early_leaving_points or 0.0)
            rec.penalty_score = rec.penalty_count * (config.penalty_points or 0.0)
            rec.bonus_score = rec.bonus_count * (config.bonus_points or 0.0)
            raw_admin_score = (
                100.0
                + rec.absence_score
                + rec.late_score
                + rec.early_leaving_score
                + rec.penalty_score
                + rec.bonus_score
            )
            rec.admin_score = min(100.0, max(0.0, raw_admin_score))


    @api.depends('skill_average_score', 'manual_score', 'admin_score', 'total_score_manual_override')
    def _compute_total_score(self):
        for rec in self:
            if not rec.total_score_manual_override:
                rec.total_score = (((rec.skill_average_score or 0.0) + (rec.manual_score or 0.0)) * 0.7) + ((rec.admin_score or 0.0) * 0.3)

    def _inverse_total_score(self):
        for rec in self:
            rec.total_score_manual_override = True

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

    @api.depends('hr_manager_ids', 'hr_employee_ids')
    def _compute_single_access_fields(self):
        for rec in self:
            rec.hr_manager_id = rec.hr_manager_ids[:1].id or False
            rec.hr_employee_id = rec.hr_employee_ids[:1].id or False

    def _inverse_hr_manager_id(self):
        for rec in self:
            rec.hr_manager_ids = [(6, 0, [rec.hr_manager_id.id] if rec.hr_manager_id else [])]

    def _inverse_hr_employee_id(self):
        for rec in self:
            rec.hr_employee_ids = [(6, 0, [rec.hr_employee_id.id] if rec.hr_employee_id else [])]

    @api.constrains('hr_manager_ids', 'hr_employee_ids')
    def _check_single_access_person(self):
        for rec in self:
            selected_employees = rec._get_selected_access_employees()
            if len(selected_employees) > 1:
                raise ValidationError(_(
                    "Only one person can be selected to access the appraisal form."
                ))

    @api.constrains('manual_score', 'manual_score_reason')
    def _check_score_limits(self):
        for rec in self:
            if rec.manual_score < 0 or rec.manual_score > 15:
                raise ValidationError(_("Manual score must be between 0 and 15."))
            if rec.manual_score and not rec.manual_score_reason:
                raise ValidationError(_("Score reason is mandatory when manual score is set."))

    @api.onchange('manual_score')
    def _onchange_manual_score(self):
        for rec in self:
            rec.total_score_manual_override = False
            if rec.manual_score < 0:
                rec.manual_score = 0
            if rec.manual_score > 15:
                rec.manual_score = 15
            max_by_total = max(0.0, (100.0 / 0.7) - (rec.skill_average_score or 0.0))
            if rec.manual_score > max_by_total:
                rec.manual_score = max_by_total
                return {
                    'warning': {
                        'title': _("Score adjusted"),
                        'message': _(
                            "Manual score was reduced so the weighted total does not exceed 100%%."
                        ),
                    }
                }

    def action_refresh_administration_score(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ─── CRUD restrictions ────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Only HR Officers and Administrators can create appraisals."""
        self._check_hr_or_admin_access("create appraisals")
        vals['state'] = 'draft'
        if vals.get('employee_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            if employee.company_id:
                vals['company_id'] = employee.company_id.id
        vals = self._apply_default_manager_to_vals(vals)
        record = super().create(vals)
        return record

    def write(self, vals):
        """Restrict writes by role and appraisal access plan."""
        # Keep appraisal company aligned with selected employee company.
        if vals.get('employee_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            if employee.company_id:
                vals['company_id'] = employee.company_id.id
        is_admin = self.env.user.has_group('sl_appraisal.group_appraisal_administrator') or self.env.user.has_group('base.group_system')
        is_hr_officer = self.env.user.has_group('sl_appraisal.group_appraisal_hr')
        is_manager = self.env.user.has_group('sl_appraisal.group_appraisal_manager') or is_hr_officer

        # Total score is admin-only and editable only in Submitted stage.
        if 'total_score' in vals:
            if not is_admin:
                raise AccessError(_("Only Appraisal Administrators can edit Total Score."))
            for rec in self:
                if rec.state != 'submitted':
                    raise AccessError(_("Total Score can only be edited in Submitted stage."))



        if is_hr_officer and not is_admin:
            hr_always_allowed = {'hr_manager_ids', 'hr_employee_ids'}
            for rec in self:
                if rec.state == 'draft':
                    continue
                if set(vals) <= hr_always_allowed:
                    continue
                allowed_users = rec._get_selected_access_employees().mapped('user_id')
                if self.env.user not in allowed_users:
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

    def _get_skill_level_for_job_sync(self, skill):
        """Return the employee's level for a skill, or the type default level."""
        self.ensure_one()
        employee = self.employee_id
        emp_skill = employee.employee_skill_ids.filtered(
            lambda s: s.skill_id.id == skill.id
        )
        if emp_skill:
            return emp_skill.skill_level_id
        return skill.skill_type_id.skill_level_ids.filtered(
            lambda level: level.default_level
        )[:1]

    def _sync_skill_lines_from_job_position(self):
        """Add job skills missing on the appraisal; update levels; keep existing lines."""
        self.ensure_one()
        employee = self.employee_id
        if not employee.job_id:
            raise UserError(
                _("Employee %s has no job position assigned.") % employee.name
            )
        employee.action_add_data_from_job_position()

        job_skills = employee.job_id.skill_ids
        existing_lines = self.appraisal_skill_line_ids
        existing_skill_ids = set(existing_lines.mapped('skill_id').ids)
        create_commands = []

        for skill in job_skills:
            level = self._get_skill_level_for_job_sync(skill)
            if skill.id in existing_skill_ids:
                if not level:
                    continue
                line = existing_lines.filtered(lambda l: l.skill_id.id == skill.id)
                line.write({'current_skill_level_id': level.id})
            elif level:
                create_commands.append(Command.create({
                    'skill_type_id': skill.skill_type_id.id,
                    'skill_id': skill.id,
                    'current_skill_level_id': level.id,
                }))

        if create_commands:
            self.write({'appraisal_skill_line_ids': create_commands})
        if job_skills or existing_lines:
            self.skills_populated = True

    def action_refresh_skills_from_job(self):
        """Refresh appraisal skills from the employee job position (draft only)."""
        drafts = self.filtered(lambda a: a.state == 'draft')
        if not drafts:
            raise UserError(_("Skills can only be refreshed on draft appraisals."))
        if self - drafts:
            raise UserError(
                _("Some selected appraisals are not in Draft and were skipped. "
                  "Open draft appraisals only.")
            )
        for appraisal in drafts:
            if not appraisal.employee_id:
                raise UserError(_("Please select an employee first."))
            appraisal._sync_skill_lines_from_job_position()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Refresh Skills'),
                'type': 'success',
                'message': _('Skills refreshed from job position for %s appraisal(s).')
                % len(drafts),
            },
        }

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

        force_batch_submit = self.env.context.get('batch_force_submit') and self._is_hr_or_admin()
        is_selected_user = self.env.user in self._get_selected_access_employees().mapped('user_id')
        if not is_selected_user and not force_batch_submit:
            raise AccessError(_("Only selected manager/employee can submit."))

        # On submit, initialize HR score from manager feedback score once.
        for line in self.sudo().appraisal_skill_line_ids:
            if not line.hr_skill_score_level_id and line.manager_feedback_skill_level_id:
                line.hr_skill_score_level_id = line.manager_feedback_skill_level_id

        if force_batch_submit:
            self.sudo().write({'state': 'submitted'})
        else:
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
            rec.total_score_manual_override = False
            if rec.employee_id.company_id:
                rec.company_id = rec.employee_id.company_id
            if not rec.hr_manager_ids and rec.employee_id.parent_id.user_id:
                rec.hr_manager_ids = rec.employee_id.parent_id
            if rec.hr_manager_ids:
                rec.hr_manager_ids = rec.hr_manager_ids & rec.allowed_manager_ids

    @api.model
    def _apply_default_manager_to_vals(self, vals):
        if vals.get('employee_id') and 'hr_manager_ids' not in vals:
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            if employee.parent_id.user_id:
                vals['hr_manager_ids'] = [(6, 0, employee.parent_id.ids)]
        return vals

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
