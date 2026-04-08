from odoo import api, fields, models, _
from odoo.exceptions import AccessError


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

    def write(self, vals):
        for rec in self:
            appraisal = rec.appraisal_id
            if appraisal.state == 'draft' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in Draft."))
            if appraisal.state == 'hr_finalization' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in HR Finalization."))
            if appraisal.state == 'published' and not appraisal._is_hr_or_admin():
                allowed = {'proposed_skill_level_id', 'manager_notes'}
                if not set(vals).issubset(allowed):
                    raise AccessError(_("Managers/coach can edit only proposed level and manager notes in Published."))
        return super().write(vals)
