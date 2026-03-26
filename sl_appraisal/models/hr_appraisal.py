from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError, AccessError


class HrAppraisal(models.Model):
    _inherit = 'hr.appraisal'

    # ── State field (replaces old Kanban stages) ──────────────────────
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('hr_finalization', 'HR Finalization'),
    ], string='Status', default='draft', tracking=True, copy=False,
        help="Draft: HR prepares appraisal.\n"
             "Published: Surveys sent to evaluators.\n"
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

    # ─── Overrides ────────────────────────────────────────────────────

    @api.depends('appraisal_skill_line_ids')
    def _compute_skill_line_count(self):
        for rec in self:
            rec.skill_line_count = len(rec.appraisal_skill_line_ids)

    @api.depends_context('uid')
    def _compute_is_hr_or_admin(self):
        is_hr = self.env.user.has_group(
            'samalink_security_groups.group_samalink_hr_officer')
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            rec.is_hr_or_admin = is_hr or is_admin

    # ─── CRUD restrictions ────────────────────────────────────────────

    @api.model
    def create(self, vals):
        """Only HR Officers and Administrators can create appraisals."""
        self._check_hr_or_admin_access("create appraisals")
        vals['state'] = 'draft'
        record = super().create(vals)
        return record

    def write(self, vals):
        """Prevent non-HR users from changing state directly."""
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
        """Move appraisal from Draft → Published and send survey emails."""
        self.ensure_one()
        self._check_hr_or_admin_access("publish appraisals")
        if self.state != 'draft':
            raise UserError(_("Only draft appraisals can be published."))
        # Validate that at least one evaluator is set
        if not self.hr_manager_ids and not self.hr_emp:
            raise UserError(
                _("Please assign at least one evaluator (managers or "
                  "employee) before publishing."))
        self.write({'state': 'published'})
        # Send survey emails using existing mechanism
        self.action_start_appraisal()

    def action_hr_finalize(self):
        """Move appraisal from Published → HR Finalization.
        Auto-update employee skills with approved levels."""
        self.ensure_one()
        self._check_hr_or_admin_access("finalize appraisals")
        if self.state != 'published':
            raise UserError(
                _("Only published appraisals can be finalized."))
        self.write({'state': 'hr_finalization'})
        # Auto-update employee skills
        self._update_employee_skills()

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
            'samalink_security_groups.group_samalink_hr_officer')
            or self.env.user.has_group('base.group_system'))

    def _check_hr_or_admin_access(self, action_name):
        if not self._is_hr_or_admin():
            raise AccessError(
                _("Only HR Officers and Administrators can %s.",
                  action_name))

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
