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

    manager_feedback_skill_level_id = fields.Many2one(
        'hr.skill.level',
        string='Manager Feedback Score',
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="Manager selected score for this skill line.")

    manager_feedback_level_progress = fields.Integer(
        related='manager_feedback_skill_level_id.level_progress',
        string='Manager Feedback %',
        readonly=True)

    computed_current_level_progress = fields.Integer(
        string='Current %',
        compute='_compute_computed_current_level_progress',
        store=True,
        help="Displayed current percentage based on manager feedback score.")

    hr_skill_score_level_id = fields.Many2one(
        'hr.skill.level',
        string='HR Skill Score',
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="HR selected score copied initially from manager feedback score.")

    hr_skill_score_level_progress = fields.Integer(
        related='hr_skill_score_level_id.level_progress',
        string='HR Skill %',
        readonly=True)

    final_skill_level_id = fields.Many2one(
        'hr.skill.level', string='Final Level (HR)',
        domain="[('skill_type_id', '=', skill_type_id)]",
        help="Final skill level approved by HR. "
             "This will be applied to the employee card.")

    final_level_progress = fields.Integer(
        related='final_skill_level_id.level_progress',
        string='Final Progress', readonly=True)

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

    # ── Computed: level change indicator ──────────────────────────────
    level_change = fields.Selection([
        ('improved', '↑ Improved'),
        ('same', '→ Same'),
        ('declined', '↓ Declined'),
        ('new', '★ New'),
    ], string='Change', compute='_compute_level_change', store=True)

    @api.depends(
        'state',
        'manager_feedback_skill_level_id',
        'manager_feedback_level_progress',
        'hr_skill_score_level_id',
        'hr_skill_score_level_progress',
        'current_level_progress',
    )
    def _compute_computed_current_level_progress(self):
        for line in self:
            if line.state == 'published':
                line.computed_current_level_progress = (
                    line.manager_feedback_level_progress
                    if line.manager_feedback_skill_level_id
                    else (line.current_level_progress or 0)
                )
            elif line.state in ('submitted', 'hr_finalization'):
                line.computed_current_level_progress = (
                    line.hr_skill_score_level_progress
                    if line.hr_skill_score_level_id
                    else (
                        line.manager_feedback_level_progress
                        if line.manager_feedback_skill_level_id
                        else (line.current_level_progress or 0)
                    )
                )
            else:
                line.computed_current_level_progress = line.current_level_progress or 0

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
        self.manager_feedback_skill_level_id = False
        self.hr_skill_score_level_id = False

    @api.onchange('current_skill_level_id')
    def _onchange_current_skill_level_id_default_manager_score(self):
        for rec in self:
            if rec.current_skill_level_id and not rec.manager_feedback_skill_level_id:
                rec.manager_feedback_skill_level_id = rec.current_skill_level_id

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

    def write(self, vals):
        for rec in self:
            appraisal = rec.appraisal_id
            is_admin = (
                appraisal.env.user.has_group('sl_appraisal.group_appraisal_administrator')
                or appraisal.env.user.has_group('base.group_system')
            )
            is_hr = appraisal.env.user.has_group('sl_appraisal.group_appraisal_hr')
            is_manager = appraisal.env.user.has_group('sl_appraisal.group_appraisal_manager')
            if is_admin and {'manager_feedback_skill_level_id', 'current_skill_level_id'} & set(vals):
                raise AccessError(_("Administrator cannot edit Manager Feedback Score or Current Level fields."))
            if appraisal.state == 'draft' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in Draft."))
            if appraisal.state == 'submitted' and not is_admin:
                raise AccessError(_("Only Appraisal Administrator can edit skill lines in Submitted state."))
            if appraisal.state == 'hr_finalization' and not appraisal._is_hr_or_admin():
                raise AccessError(_("Only HR/Admin can edit skill lines in HR Finalization."))
            if appraisal.state == 'published' and not appraisal._is_hr_or_admin():
                allowed_manager_vals = {'manager_feedback_skill_level_id'}
                if not is_manager or not set(vals).issubset(allowed_manager_vals):
                    raise AccessError(_("Managers can update only Manager Feedback Score in Published stage."))
            if appraisal.state == 'published' and is_hr and not is_admin:
                allowed_hr_vals = {'manager_feedback_skill_level_id'}
                if not set(vals).issubset(allowed_hr_vals):
                    raise AccessError(_("HR Officer can update only Manager Feedback Score in Published stage."))
            if appraisal.state in ('submitted', 'hr_finalization') and is_hr and not is_admin:
                raise AccessError(_("HR Officer cannot edit skill lines after submission."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            current_level_id = vals.get('current_skill_level_id')
            if current_level_id and not vals.get('manager_feedback_skill_level_id'):
                vals['manager_feedback_skill_level_id'] = current_level_id
        return super().create(vals_list)
