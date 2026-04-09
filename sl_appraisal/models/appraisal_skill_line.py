from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class AppraisalSkillLine(models.Model):
    """Links each skill to an appraisal for evaluation.
    Tracks current → proposed (by manager) → final (by HR) skill levels."""
    _name = 'appraisal.skill.line'
    _description = 'Appraisal Skill Evaluation Line'
    _order = 'skill_type_id, skill_id'

    appraisal_id = fields.Many2one(
        'hr.appraisal', string='Appraisal',
        required=True, ondelete='cascade', index=True)

    employee_id = fields.Many2one(
        related='appraisal_id.employee_id',
        string='Employee', store=True, readonly=True)

    state = fields.Selection(
        related='appraisal_id.state',
        string='Appraisal State', store=True, readonly=True)

    # ── Skill identification ──────────────────────────────────────────
    skill_type_id = fields.Many2one(
        'hr.skill.type', string='Skill Type', required=True,
        help="Category of the skill (e.g., Languages, Technical, Soft Skills)")

    skill_id = fields.Many2one(
        'hr.skill', string='Skill', required=True,
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="Specific skill being evaluated")

    # ── Levels ────────────────────────────────────────────────────────
    current_skill_level_id = fields.Many2one(
        'hr.skill.level', string='Current Level',
        domain="[('skill_type_id', '=', skill_type_id)]",
        readonly=True,
        help="Employee's current skill level at the time of appraisal")

    current_level_progress = fields.Integer(
        related='current_skill_level_id.level_progress',
        string='Current Progress', readonly=True)

    proposed_skill_level_id = fields.Many2one(
        'hr.skill.level', string='Proposed Level',
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="Skill level proposed by the evaluating manager")

    proposed_level_progress = fields.Integer(
        related='proposed_skill_level_id.level_progress',
        string='Proposed Progress', readonly=True)

    final_skill_level_id = fields.Many2one(
        'hr.skill.level', string='Final Level (HR)',
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="Final skill level approved by HR. "
             "This will be applied to the employee card.")

    final_level_progress = fields.Integer(
        related='final_skill_level_id.level_progress',
        string='Final Progress', readonly=True)

    # ── Survey link (optional) ────────────────────────────────────────
    survey_question_id = fields.Many2one(
        'survey.question', string='Linked Survey Question',
        help="Optional: link this skill evaluation to a specific survey question")

    # ── Notes ─────────────────────────────────────────────────────────
    manager_notes = fields.Text(
        string='Manager Notes',
        help="Manager's evaluation notes and justification")

    hr_notes = fields.Text(
        string='HR Notes',
        help="HR comments and decision rationale")

    manager_feedback_ids = fields.One2many(
        'appraisal.skill.manager.feedback',
        'skill_line_id',
        string='Manager Feedback')

    manager_feedback_count = fields.Integer(
        string='Manager Feedback',
        compute='_compute_manager_feedback_count')

    feedback_summary = fields.Char(
        string='Feedback Summary',
        compute='_compute_manager_feedback_count')

    suggested_final_skill_level_id = fields.Many2one(
        'hr.skill.level',
        string='Suggested HR Level',
        compute='_compute_suggested_final_skill_level',
        store=True,
        help="Suggested level based on managers feedback (majority vote).")

    # ── Computed: level change indicator ──────────────────────────────
    level_change = fields.Selection([
        ('improved', '↑ Improved'),
        ('same', '→ Same'),
        ('declined', '↓ Declined'),
        ('new', '★ New'),
    ], string='Change', compute='_compute_level_change', store=True)

    @api.depends('current_skill_level_id', 'final_skill_level_id')
    def _compute_level_change(self):
        for line in self:
            if not line.final_skill_level_id:
                line.level_change = False
            elif not line.current_skill_level_id:
                line.level_change = 'new'
            elif line.final_skill_level_id.level_progress > line.current_skill_level_id.level_progress:
                line.level_change = 'improved'
            elif line.final_skill_level_id.level_progress < line.current_skill_level_id.level_progress:
                line.level_change = 'declined'
            else:
                line.level_change = 'same'

    @api.onchange('skill_type_id')
    def _onchange_skill_type_id(self):
        """Clear skill and levels when skill type changes."""
        self.skill_id = False
        self.proposed_skill_level_id = False
        self.final_skill_level_id = False

    @api.depends('manager_feedback_ids')
    def _compute_manager_feedback_count(self):
        for rec in self:
            rec.manager_feedback_count = len(rec.manager_feedback_ids)
            if rec.manager_feedback_count:
                rec.feedback_summary = _("%s feedback entries") % rec.manager_feedback_count
            else:
                rec.feedback_summary = _("No feedback yet")

    @api.depends(
        'manager_feedback_ids.proposed_skill_level_id',
        'manager_feedback_ids.proposed_skill_level_id.level_progress',
    )
    def _compute_suggested_final_skill_level(self):
        """Majority vote from managers.

        Tie-breaker: higher level_progress wins.
        """
        for rec in self:
            votes = {}
            for feedback in rec.manager_feedback_ids.filtered(lambda f: f.proposed_skill_level_id):
                level = feedback.proposed_skill_level_id
                bucket = votes.setdefault(level.id, {
                    'level': level,
                    'count': 0,
                    'progress': level.level_progress or 0,
                })
                bucket['count'] += 1

            if not votes:
                rec.suggested_final_skill_level_id = False
                continue

            ranked = sorted(
                votes.values(),
                key=lambda item: (item['count'], item['progress']),
                reverse=True,
            )
            rec.suggested_final_skill_level_id = ranked[0]['level'].id

    def action_open_my_feedback(self):
        self.ensure_one()
        appraisal = self.appraisal_id
        if appraisal.state != 'published':
            raise UserError(_("You can submit manager feedback only in Published state."))
        if self.env.user not in appraisal.access_user_ids and not appraisal._is_hr_or_admin():
            raise AccessError(_("You are not allowed to access this appraisal."))

        employee = self.env.user.employee_id

        feedback_model = self.env['appraisal.skill.manager.feedback']
        domain = [('skill_line_id', '=', self.id)]
        if appraisal._is_hr_or_admin():
            action_name = _("All Manager Feedback")
        else:
            domain.append(('manager_user_id', '=', self.env.user.id))
            action_name = _("My Feedback")
        existing = feedback_model.search(domain, limit=1)
        if not existing and not appraisal._is_hr_or_admin():
            existing = feedback_model.create({
                'skill_line_id': self.id,
                'manager_user_id': self.env.user.id,
            })
        return {
            'name': action_name,
            'type': 'ir.actions.act_window',
            'res_model': 'appraisal.skill.manager.feedback',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('sl_appraisal.sl_manager_feedback_view_tree').id, 'list'),
                (self.env.ref('sl_appraisal.sl_manager_feedback_view_form').id, 'form'),
            ],
            'domain': domain,
            'context': {
                'default_skill_line_id': self.id,
                'default_manager_user_id': self.env.user.id,
            },
            'target': 'current',
            'res_id': existing.id if existing and len(existing) == 1 else False,
        }

    def action_apply_suggested_final_level(self):
        self.ensure_one()
        appraisal = self.appraisal_id
        if not appraisal._is_hr_or_admin():
            raise AccessError(_("Only HR/Admin can apply suggested levels."))
        if not self.suggested_final_skill_level_id:
            raise UserError(_("No suggested level available for this skill line yet."))
        self.write({'final_skill_level_id': self.suggested_final_skill_level_id.id})
        return True

    def write(self, vals):
        for rec in self:
            appraisal = rec.appraisal_id
            if appraisal.state == 'draft' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in Draft."))
            if appraisal.state == 'hr_finalization' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in HR Finalization."))
            if appraisal.state == 'published' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Managers/coach must use the 'My Feedback' action to submit feedback."))
        return super().write(vals)
