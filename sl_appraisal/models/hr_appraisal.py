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

    my_survey_count = fields.Integer(
        string='My Survey Links',
        compute='_compute_my_survey_count')

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

    manual_score_display = fields.Float(
        string='Score Tab Value (%)',
        related='manual_score',
        readonly=True,
        help="Displays the score entered in the Score tab.")

    total_score = fields.Float(
        string='Total Score (%)',
        compute='_compute_scores',
        store=True,
        digits=(16, 2),
        help="Sum of Skills Average and Manual Score.")

    manual_score_reason = fields.Text(
        string='Score Reason',
        help="Reason for the manual score adjustment.")

    # ─── Overrides ────────────────────────────────────────────────────

    @api.depends('appraisal_skill_line_ids')
    def _compute_skill_line_count(self):
        for rec in self:
            rec.skill_line_count = len(rec.appraisal_skill_line_ids)

    def _compute_my_survey_count(self):
        user_partner = self.env.user.partner_id
        for rec in self:
            rec.my_survey_count = self.env['survey.user_input'].search_count([
                ('appraisal_id', '=', rec.id),
                ('partner_id', '=', user_partner.id),
            ])

    @api.depends(
        'appraisal_skill_line_ids',
        'appraisal_skill_line_ids.computed_current_level_progress',
        'appraisal_skill_line_ids.final_level_progress',
        'manual_score',
    )
    def _compute_scores(self):
        for rec in self:
            percentages = []
            for line in rec.appraisal_skill_line_ids:
                # Prefer final approved level; fallback to current level.
                value = line.final_level_progress or line.computed_current_level_progress or 0
                percentages.append(value)
            rec.skill_average_score = sum(percentages) / len(percentages) if percentages else 0.0
            rec.total_score = rec.skill_average_score + (rec.manual_score or 0.0)

    @api.depends_context('uid')
    def _compute_is_hr_or_admin(self):
        is_hr = self.env.user.has_group(
            'sl_appraisal.group_appraisal_hr')
        is_admin = self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
        for rec in self:
            rec.is_hr_or_admin = is_hr or is_admin

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
        'hr_collaborator_ids.user_id', 'hr_colleague_ids.user_id',
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
            | self.hr_collaborator_ids
            | self.hr_colleague_ids
            | self.hr_employee_ids
        ).filtered(lambda emp: emp.user_id)

    @api.constrains('hr_manager_ids', 'hr_collaborator_ids', 'hr_colleague_ids', 'hr_employee_ids')
    def _check_single_access_person(self):
        for rec in self:
            selected_employees = rec._get_selected_access_employees()
            if len(selected_employees) > 1:
                raise ValidationError(_(
                    "Only one person can be selected to access the appraisal form."
                ))

    @api.constrains('manual_score', 'manual_score_reason', 'total_score')
    def _check_score_limits(self):
        for rec in self:
            if rec.manual_score < 0 or rec.manual_score > 15:
                raise ValidationError(_("Manual score must be between 0 and 15."))
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

        if is_hr_officer and not is_admin:
            for rec in self:
                allowed_users = rec._get_selected_access_employees().mapped('user_id')
                if self.env.user not in allowed_users:
                    raise AccessError(_(
                        "You can edit this appraisal only if you are selected in the Access Plan."
                    ))

        if 'state' in vals and not self._is_hr_or_admin():
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

    def action_submit(self):
        """Move appraisal from Published -> Submitted.
        Allowed for selected manager user and appraisal administrators."""
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_("Only published appraisals can be submitted."))

        is_admin = (
            self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        )
        is_selected_user = self.env.user in self._get_selected_access_employees().mapped('user_id')
        if not (is_admin or is_selected_user):
            raise AccessError(_("Only selected manager/contributor or Appraisal Administrator can submit."))

        self.write({'state': 'submitted'})

    def action_sync_skills_from_surveys(self):
        """Sync manager proposed skill levels from completed survey answers."""
        self.ensure_one()
        if self.state not in ('published', 'hr_finalization'):
            raise UserError(_("You can sync survey answers only in Published or HR Finalization."))
        synced = self._sync_skill_lines_from_survey_answers()
        self.message_post(
            body=_("Survey answers synced to skills. Updated %s skill line(s).") % synced,
            subtype_xmlid='mail.mt_note',
        )

    def action_open_my_surveys(self):
        self.ensure_one()
        answers = self.env['survey.user_input'].search([
            ('appraisal_id', '=', self.id),
            ('partner_id', '=', self.env.user.partner_id.id),
        ], order='state asc, create_date desc')
        if not answers:
            raise UserError(_("No survey link found for your user in this appraisal."))

        # Prefer pending link, then latest completed.
        pending = answers.filtered(lambda a: a.state != 'done')
        answer = pending[:1] or answers[:1]
        return {
            'type': 'ir.actions.act_url',
            'url': answer.get_start_url(),
            'target': 'new',
        }

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
        self._sync_skill_lines_from_surveys_if_needed()
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

    def _sync_skill_lines_from_surveys_if_needed(self):
        for appraisal in self:
            appraisal._sync_skill_lines_from_survey_answers()

    def _sync_skill_lines_from_survey_answers(self):
        """Map completed survey answers to appraisal skill proposed levels.

        Mapping strategy:
        1) Skill line linked to question (`survey_question_id`)
        2) Exact skill level name match with textual answer (case-insensitive)
        3) Fallback: numeric answer mapped by nearest `level_progress`
        """
        self.ensure_one()
        if not self.appraisal_skill_line_ids:
            return 0

        answers = self.env['survey.user_input'].search([
            ('appraisal_id', '=', self.id),
            ('state', '=', 'done'),
        ])
        if not answers:
            return 0

        question_lines = {}
        for line in self.appraisal_skill_line_ids.filtered(lambda l: l.survey_question_id):
            question_lines.setdefault(line.survey_question_id.id, self.env['appraisal.skill.line'])
            question_lines[line.survey_question_id.id] |= line

        updated = 0
        for answer in answers:
            for line in answer.user_input_line_ids:
                skill_lines = question_lines.get(line.question_id.id)
                if not skill_lines:
                    continue
                for skill_line in skill_lines:
                    level = self._map_answer_to_skill_level(skill_line, line)
                    if level:
                        manager_employee = self.env['hr.employee'].search(
                            [('user_id.partner_id', '=', answer.partner_id.id)],
                            limit=1,
                        )
                        manager_user = manager_employee.user_id if manager_employee else self.env['res.users'].search(
                            [('partner_id', '=', answer.partner_id.id)],
                            limit=1,
                        )
                        if manager_user:
                            feedback = self.env['appraisal.skill.manager.feedback'].search([
                                ('skill_line_id', '=', skill_line.id),
                                ('manager_user_id', '=', manager_user.id),
                            ], limit=1)
                            feedback_vals = {
                                'proposed_skill_level_id': level.id,
                                'manager_notes': _("Auto-synced from survey answer by %s") % (
                                    answer.partner_id.name or answer.email or _("Anonymous")
                                ),
                            }
                            if feedback:
                                feedback.write(feedback_vals)
                            else:
                                feedback_vals.update({
                                    'skill_line_id': skill_line.id,
                                    'manager_user_id': manager_user.id,
                                })
                                self.env['appraisal.skill.manager.feedback'].create(feedback_vals)
                            updated += 1
        return updated

    def _map_answer_to_skill_level(self, skill_line, answer_line):
        levels = self.env['hr.skill.level'].search([
            ('skill_type_id', '=', skill_line.skill_type_id.id),
        ])
        if not levels:
            return False

        suggested_row = getattr(answer_line, 'value_suggested_row', False)
        suggested_answer = getattr(answer_line, 'suggested_answer_id', False)
        textual_candidates = [
            getattr(answer_line, 'value_text_box', False),
            getattr(answer_line, 'value_char_box', False),
            suggested_row and suggested_row.value or False,
            suggested_answer and suggested_answer.value or False,
        ]
        text_value = next((v for v in textual_candidates if v), False)
        if text_value:
            text_value = text_value.strip().lower()
            exact = levels.filtered(lambda l: (l.name or '').strip().lower() == text_value)
            if exact:
                return exact[0]

        numeric_value = getattr(answer_line, 'value_numerical_box', False)
        if numeric_value is False or numeric_value is None:
            return False
        nearest = min(levels, key=lambda lvl: abs((lvl.level_progress or 0) - numeric_value))
        return nearest

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
                    'appraisal_date': appraisal.appraisal_deadline,
                    'skill_type_id': line.skill_type_id.id,
                    'skill_id': line.skill_id.id,
                    'old_level_id': line.current_skill_level_id.id,
                    'new_level_id': line.final_skill_level_id.id,
                    'change_state': line.level_change or 'same',
                })
