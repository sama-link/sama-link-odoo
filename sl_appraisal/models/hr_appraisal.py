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
        compute='_compute_job_id',
        store=True,
        readonly=False,
        help="Defaults to the employee's current job position. For an "
             "employee who changed position during the appraisal period, "
             "the batch review wizard sets the position this appraisal is for.",
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

    # Stored so list domains can exclude "my own appraisal" WITHOUT walking
    # through hr.employee. Evaluators are granted the appraisal via
    # access_user_ids, not the employee record, and hr.employee is limited to
    # one's own team - so a domain on employee_id.user_id silently drops every
    # appraisal whose employee the evaluator cannot read, emptying their list.
    employee_user_id = fields.Many2one(
        'res.users',
        string='Employee User',
        related='employee_id.user_id',
        store=True,
        index=True,
        readonly=True,
    )

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
        string='Manual Adjustment',
        digits=(16, 2),
        help="Adjustment applied after the base score, within the limit set in "
             "Administration Score Configuration.")
    base_score = fields.Float(
        string='Base Score (%)',
        compute='_compute_base_score',
        store=True,
        digits=(16, 2),
        help="(Skills Average × 70%) + (Administration Score × 30%), before manual adjustment.",
    )

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
    admin_score_exempt = fields.Boolean(
        string='Administration Score Exempt',
        compute='_compute_administration_scores',
        help="Employee is in the administrative exclusion list and always "
             "receives a 100% administration score, regardless of absences, "
             "lateness or penalties.",
    )
    weighted_skill_score = fields.Float(
        string='Weighted Skills (70%)',
        compute='_compute_weighted_score_breakdown',
        digits=(16, 2),
        help="Skills average at 70% weight (manual adjustment is applied separately).",
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
        help="Base score plus manual adjustment (within configured limit), "
             "capped between 0 and 100. Editable by Appraisal Administrator only.")
    total_score_manual_override = fields.Boolean(
        string='Total Score Manual Override',
        default=False,
        copy=False,
    )

    manual_score_reason = fields.Text(
        string='Score Reason',
        help="Reason for the manual score adjustment.")

    has_active_contract_in_period = fields.Boolean(
        string='Has Active Contract In Period',
        compute='_compute_has_active_contract_in_period',
        compute_sudo=True,
        help="Technical flag: the employee holds a contract that overlaps "
             "the appraisal period. Used to show a warning when they don't.")

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

    @api.depends('skill_average_score', 'admin_score')
    def _compute_weighted_score_breakdown(self):
        for rec in self:
            rec.weighted_skill_score = (rec.skill_average_score or 0.0) * 0.7
            rec.weighted_admin_score = (rec.admin_score or 0.0) * 0.3

    @api.depends('weighted_skill_score', 'weighted_admin_score')
    def _compute_base_score(self):
        for rec in self:
            raw_base = (rec.weighted_skill_score or 0.0) + (rec.weighted_admin_score or 0.0)
            rec.base_score = min(100.0, max(0.0, raw_base))

    def _get_manual_score_limit(self):
        return self.env['appraisal.admin.score.config'].sudo().get_config().manual_score_limit

    def _compute_total_score_value(self):
        """Base (70/30) + manual adjustment, capped 0–100."""
        self.ensure_one()
        raw = self.base_score + (self.manual_score or 0.0)
        return min(100.0, max(0.0, raw))

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_administration_scores(self):
        incentive_model = self.env['hr.incentive'].sudo()
        absence_model = self.env['hr.absent.entry'].sudo()
        attendance_model = self.env['hr.attendance'].sudo()
        config = self.env['appraisal.admin.score.config'].sudo().get_config()
        exempt_employee_ids = set(
            self.env['appraisal.admin.score.exclude'].sudo()
            .search([]).employee_id.ids
        )
        for rec in self:
            rec.admin_score_exempt = False
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

            # Excluded employees always score 100% — skip all deductions.
            if rec.employee_id.id in exempt_employee_ids:
                rec.admin_score_exempt = True
                rec.admin_score = 100.0
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


    @api.depends(
        'base_score', 'manual_score', 'total_score_manual_override',
    )
    def _compute_total_score(self):
        for rec in self:
            if not rec.total_score_manual_override:
                rec.total_score = rec._compute_total_score_value()

    def _inverse_total_score(self):
        for rec in self:
            rec.total_score = min(100.0, max(0.0, rec.total_score or 0.0))
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

    def _grant_appraisal_manager_group(self, employees=None):
        """Grant Appraisal / Manager to Access Plan users (not while Draft)."""
        group = self.env.ref(
            'sl_appraisal.group_appraisal_manager', raise_if_not_found=False)
        if not group:
            return
        appraisals = self.filtered(lambda r: r.state != 'draft')
        if employees is None:
            if not appraisals:
                return
            employees = self.env['hr.employee']
            for rec in appraisals:
                employees |= rec._get_selected_access_employees()
        else:
            employees = employees.filtered('user_id')
        users = employees.mapped('user_id').filtered('active')
        users_to_grant = users.filtered(lambda u: group not in u.groups_id)
        if users_to_grant:
            users_to_grant.sudo().write({'groups_id': [(4, group.id)]})

    @api.depends('hr_manager_ids', 'hr_employee_ids')
    def _compute_single_access_fields(self):
        for rec in self:
            rec.hr_manager_id = rec.hr_manager_ids[:1].id or False
            rec.hr_employee_id = rec.hr_employee_ids[:1].id or False

    def _inverse_hr_manager_id(self):
        for rec in self:
            rec.hr_manager_ids = [(6, 0, [rec.hr_manager_id.id] if rec.hr_manager_id else [])]
        self.filtered(lambda r: r.state != 'draft')._grant_appraisal_manager_group()

    def _inverse_hr_employee_id(self):
        for rec in self:
            rec.hr_employee_ids = [(6, 0, [rec.hr_employee_id.id] if rec.hr_employee_id else [])]
        self.filtered(lambda r: r.state != 'draft')._grant_appraisal_manager_group()

    @api.constrains('hr_manager_ids', 'hr_employee_ids')
    def _check_single_access_person(self):
        for rec in self:
            selected_employees = rec._get_selected_access_employees()
            if len(selected_employees) > 1:
                raise ValidationError(_(
                    "Only one person can be selected to access the appraisal form."
                ))

    @api.constrains('manual_score', 'manual_score_reason', 'total_score')
    def _check_score_limits(self):
        limit = self._get_manual_score_limit()
        for rec in self:
            if rec.manual_score < -limit or rec.manual_score > limit:
                raise ValidationError(
                    _("Manual adjustment must be between -%(limit)g and +%(limit)g.",
                      limit=limit)
                )
            if limit == 0 and rec.manual_score != 0:
                raise ValidationError(
                    _("Manual adjustment is disabled (limit is 0 in configuration).")
                )
            if rec.manual_score != 0 and not rec.manual_score_reason:
                raise ValidationError(
                    _("Score reason is mandatory when a manual adjustment is set.")
                )
            if rec.total_score < 0 or rec.total_score > 100:
                raise ValidationError(
                    _("Total score must be between 0 and 100.")
                )

    @api.onchange('manual_score')
    def _onchange_manual_score(self):
        limit = self._get_manual_score_limit()
        for rec in self:
            rec.total_score_manual_override = False
            if limit == 0:
                rec.manual_score = 0.0
            elif rec.manual_score < -limit:
                rec.manual_score = -limit
            elif rec.manual_score > limit:
                rec.manual_score = limit
            base = (
                (rec.skill_average_score or 0.0) * 0.7
                + (rec.admin_score or 0.0) * 0.3
            )
            max_adj = 100.0 - base
            min_adj = -base
            if rec.manual_score > max_adj:
                rec.manual_score = max_adj
                return {
                    'warning': {
                        'title': _("Score adjusted"),
                        'message': _(
                            "Manual adjustment was reduced so the total score does not exceed 100%%."
                        ),
                    }
                }
            if rec.manual_score < min_adj:
                rec.manual_score = min_adj
                return {
                    'warning': {
                        'title': _("Score adjusted"),
                        'message': _(
                            "Manual adjustment was increased so the total score is not below 0%%."
                        ),
                    }
                }

    def action_refresh_administration_score(self):
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    # ─── CRUD restrictions ────────────────────────────────────────────

    _BATCH_SYNC_FIELDS = frozenset({'appraisal_deadline', 'date_from', 'date_to'})

    @api.constrains('appraisal_deadline')
    def _check_appraisal_deadline(self):
        """Replace oh_appraisal check: loop records (batch sync writes many at once)."""
        if self.env.context.get('appraisal_batch_sync'):
            return
        today = fields.Date.today()
        for appraisal in self:
            if appraisal.appraisal_deadline and appraisal.appraisal_deadline < today:
                raise ValidationError(
                    _("Appraisal deadline cannot be in the past.")
                )

    @api.constrains('employee_id')
    def _check_employee_appraisal_eligible(self):
        """Employees with the "Appraisal" box unchecked on their employee
        card (Appraisal & Bonus tab) cannot take appraisals. The pickers
        already hide them; this is the server-side guard."""
        for appraisal in self:
            employee = appraisal.employee_id
            if employee and not employee.appraisal_eligible:
                raise ValidationError(_(
                    "%s is not eligible for appraisals: the 'Appraisal' box is "
                    "unchecked on the employee card (Appraisal & Bonus tab).",
                    employee.name,
                ))

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
        return super().create(vals)

    def write(self, vals):
        """Restrict writes by role and appraisal access plan."""
        if (
            self.env.context.get('appraisal_batch_sync')
            and set(vals) <= self._BATCH_SYNC_FIELDS
        ):
            return super(HrAppraisal, self).write(vals)

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
            vals['total_score'] = min(100.0, max(0.0, vals['total_score'] or 0.0))
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
        access_fields = {'hr_manager_ids', 'hr_employee_ids', 'hr_manager_id', 'hr_employee_id'}
        grant_after_write = bool(access_fields & set(vals))
        if vals.get('state') and vals['state'] != 'draft':
            grant_after_write = True
        result = super().write(vals)
        if grant_after_write:
            self.filtered(lambda r: r.state != 'draft')._grant_appraisal_manager_group()
        return result

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

    def _sync_skill_lines_from_employee(self):
        """Mirror appraisal skill lines from the employee card (draft appraisals only)."""
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            raise UserError(_("Please select an employee first."))

        emp_skills = employee.employee_skill_ids
        existing_lines = self.appraisal_skill_line_ids
        emp_skill_ids = set(emp_skills.mapped('skill_id').ids)
        create_commands = []

        for emp_skill in emp_skills:
            skill = emp_skill.skill_id
            line = existing_lines.filtered(lambda l: l.skill_id.id == skill.id)
            if line:
                line.sudo().write({
                    'skill_type_id': emp_skill.skill_type_id.id,
                    'current_skill_level_id': emp_skill.skill_level_id.id,
                })
            else:
                create_commands.append(Command.create({
                    'skill_type_id': emp_skill.skill_type_id.id,
                    'skill_id': skill.id,
                    'current_skill_level_id': emp_skill.skill_level_id.id,
                }))

        lines_to_remove = existing_lines.filtered(
            lambda l: l.skill_id.id not in emp_skill_ids
        )
        if lines_to_remove:
            lines_to_remove.sudo().unlink()
        if create_commands:
            self.sudo().write({'appraisal_skill_line_ids': create_commands})

        self.skills_populated = bool(emp_skills)

    def action_refresh_skills_from_job(self):
        """Refresh draft appraisal skill lines from the employee card."""
        drafts = self.filtered(lambda a: a.state == 'draft')
        if not drafts:
            raise UserError(_("Skills can only be refreshed on draft appraisals."))
        if self - drafts:
            raise UserError(
                _("Some selected appraisals are not in Draft and were skipped. "
                  "Open draft appraisals only.")
            )
        for appraisal in drafts:
            appraisal._sync_skill_lines_from_employee()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
        Allowed for selected manager/employee or Appraisal Administrator."""
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_("Only published appraisals can be submitted."))

        force_batch_submit = self.env.context.get('batch_force_submit') and self._is_hr_or_admin()
        if not self._can_submit_appraisal() and not force_batch_submit:
            raise AccessError(_("Only selected manager/employee can submit."))

        self._sync_skill_lines_hr_from_manager_feedback()

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

    # ─── Bulk workflow actions (list-view "Actions" gear menu) ────────

    def _notify_batch_result(self, title, done_count, skipped_count, skipped_reason):
        message = _("%(count)s appraisal(s) updated.", count=done_count)
        if skipped_count:
            message += " " + _(
                "Skipped %(count)s record(s) %(reason)s.",
                count=skipped_count, reason=skipped_reason,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success',
                'sticky': bool(skipped_count),
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_batch_publish(self):
        """Bulk Draft → Published from the list-view Actions menu."""
        self._check_hr_or_admin_access("publish appraisals")
        to_do = self.filtered(lambda a: a.state == 'draft')
        skipped = self - to_do
        if not to_do:
            raise UserError(_("No appraisals in Draft state were selected."))
        for appraisal in to_do:
            appraisal.action_publish()
        return self._notify_batch_result(
            _("Appraisals Published"), len(to_do), len(skipped),
            _("not in Draft state"))

    def action_batch_submit(self):
        """Bulk Published → Submitted from the list-view Actions menu."""
        to_do = self.filtered(lambda a: a.state == 'published')
        skipped = self - to_do
        if not to_do:
            raise UserError(_("No appraisals in Published state were selected."))
        for appraisal in to_do:
            appraisal.action_submit()
        return self._notify_batch_result(
            _("Appraisals Submitted"), len(to_do), len(skipped),
            _("not in Published state"))

    def action_batch_hr_finalize(self):
        """Bulk Submitted → HR Finalization from the list-view Actions menu."""
        to_do = self.filtered(lambda a: a.state == 'submitted')
        skipped = self - to_do
        if not to_do:
            raise UserError(_("No appraisals in Submitted state were selected."))
        for appraisal in to_do:
            appraisal.action_hr_finalize()
        return self._notify_batch_result(
            _("Appraisals Finalized"), len(to_do), len(skipped),
            _("not in Submitted state"))

    def action_batch_reset_to_draft(self):
        """Bulk reset to Draft from the list-view Actions menu."""
        self._check_hr_or_admin_access("reset appraisals to draft")
        to_do = self.filtered(lambda a: a.state != 'draft')
        skipped = self - to_do
        if not to_do:
            raise UserError(_("All selected appraisals are already in Draft state."))
        for appraisal in to_do:
            appraisal.action_reset_to_draft()
        return self._notify_batch_result(
            _("Appraisals Reset to Draft"), len(to_do), len(skipped),
            _("already in Draft state"))

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

    def _is_appraisal_administrator_user(self):
        return (
            self.env.user.has_group('sl_appraisal.group_appraisal_administrator')
            or self.env.user.has_group('base.group_system')
        )

    def _can_submit_appraisal(self):
        """Selected evaluator, or Appraisal Administrator / system admin."""
        self.ensure_one()
        if self.env.user in self._get_selected_access_employees().mapped('user_id'):
            return True
        return self._is_appraisal_administrator_user()

    def _sync_skill_lines_hr_from_manager_feedback(self):
        """Copy manager feedback skill level to HR skill score on all skill lines."""
        for appraisal in self:
            appraisal.sudo().appraisal_skill_line_ids._sync_hr_score_from_manager()

    def action_sync_hr_scores_from_manager(self):
        """Fix submitted appraisals: overwrite HR skill score from manager feedback."""
        self._check_hr_or_admin_access("sync HR skill scores from manager feedback")
        to_sync = self.filtered(lambda a: a.state == 'submitted')
        skipped = self - to_sync
        if not to_sync:
            raise UserError(_("No appraisals in Submitted state were selected."))
        to_sync._sync_skill_lines_hr_from_manager_feedback()
        message = _(
            "Synced HR skill scores from manager feedback for %(count)s appraisal(s).",
            count=len(to_sync),
        )
        if skipped:
            message += " " + _(
                "Skipped %(count)s record(s) not in Submitted state.",
                count=len(skipped),
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("HR Scores Synced"),
                'message': message,
                'type': 'success',
                'sticky': bool(skipped),
            },
        }

    def _check_hr_or_admin_access(self, action_name):
        if not self._is_hr_or_admin():
            raise AccessError(
                _("Only HR Officers and Administrators can %s.",
                  action_name))

    @api.depends('employee_id')
    def _compute_job_id(self):
        """Job Position follows the employee unless it was set explicitly
        (e.g. by the batch review wizard for an employee who changed job in
        the period — values given on create/write are kept)."""
        for rec in self:
            rec.job_id = rec.employee_id.job_id

    @api.depends('employee_id', 'date_from', 'date_to')
    def _compute_has_active_contract_in_period(self):
        for rec in self:
            rec.has_active_contract_in_period = (
                not rec.employee_id
                or rec.employee_id._has_active_contract_in_period(
                    rec.date_from, rec.date_to)
            )

    @api.onchange('employee_id', 'date_from', 'date_to')
    def _onchange_warn_no_contract_in_period(self):
        if (
            self.employee_id and self.date_from and self.date_to
            and not self.employee_id._has_active_contract_in_period(
                self.date_from, self.date_to)
        ):
            return {
                'warning': {
                    'title': _("No active contract in this period"),
                    'message': _(
                        "%(employee)s has no active contract covering the "
                        "appraisal period %(date_from)s → %(date_to)s. "
                        "Check the hire/departure dates before appraising."
                    ) % {
                        'employee': self.employee_id.name,
                        'date_from': self.date_from,
                        'date_to': self.date_to,
                    },
                }
            }

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
