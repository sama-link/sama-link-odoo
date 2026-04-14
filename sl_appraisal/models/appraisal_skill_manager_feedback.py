from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class AppraisalSkillManagerFeedback(models.Model):
    _name = 'appraisal.skill.manager.feedback'
    _description = 'Manager Skill Feedback'
    _order = 'write_date desc, id desc'
    _rec_name = 'manager_employee_id'

    skill_line_id = fields.Many2one(
        'appraisal.skill.line', required=True, ondelete='cascade', index=True)
    appraisal_id = fields.Many2one(
        'hr.appraisal', related='skill_line_id.appraisal_id', store=True, index=True, readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', related='skill_line_id.employee_id', store=True, readonly=True)
    manager_user_id = fields.Many2one(
        'res.users', required=False, index=True,
        default=lambda self: self.env.user,
        help="Manager/coach user who provided this feedback.")
    manager_employee_id = fields.Many2one(
        'hr.employee',
        compute='_compute_manager_employee_id',
        compute_sudo=True,
        store=True,
        readonly=True,
        help="Employee card linked to manager user (optional).")
    skill_type_id = fields.Many2one(
        'hr.skill.type', related='skill_line_id.skill_type_id', store=True, readonly=True)
    skill_id = fields.Many2one(
        'hr.skill', related='skill_line_id.skill_id', store=True, readonly=True)
    proposed_skill_level_id = fields.Many2one(
        'hr.skill.level',
        domain="[('skill_type_id', '=', skill_type_id)]",
        string='Manager Proposed Level',
        required=False)
    manager_notes = fields.Text(string='Manager Notes')

    _sql_constraints = [
        (
            'uniq_skillline_manager_feedback',
            'unique(skill_line_id, manager_user_id)',
            'Each manager can submit only one feedback per skill line.',
        ),
    ]

    @api.depends('manager_user_id')
    def _compute_manager_employee_id(self):
        emp_model = self.env['hr.employee'].sudo()
        for rec in self:
            if rec.manager_user_id:
                rec.manager_employee_id = emp_model.search(
                    [('user_id', '=', rec.manager_user_id.id)],
                    limit=1,
                )
            else:
                rec.manager_employee_id = False

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_manager_self_write()
        return records

    def write(self, vals):
        self._check_manager_self_write()
        return super().write(vals)

    def _check_manager_self_write(self):
        if self.env.user.has_group('sl_appraisal.group_appraisal_hr') or self.env.user.has_group('base.group_system'):
            return
        for rec in self:
            if rec.appraisal_id.state != 'published':
                raise AccessError(_("Manager feedback is allowed only in Published state."))
            if not rec.manager_user_id:
                raise AccessError(_("Manager user is required on feedback records."))
            if rec.manager_user_id != self.env.user:
                raise AccessError(_("You can edit only your own manager feedback."))
