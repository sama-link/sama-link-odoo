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
    manager_employee_id = fields.Many2one(
        'hr.employee', required=True, index=True,
        help="Manager/coach user who provided this feedback.")
    manager_user_id = fields.Many2one(
        'res.users', related='manager_employee_id.user_id', store=True, index=True, readonly=True)
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
            'unique(skill_line_id, manager_employee_id)',
            'Each manager can submit only one feedback per skill line.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_manager_self_write()
        return records

    def write(self, vals):
        self._check_manager_self_write()
        return super().write(vals)

    def _check_manager_self_write(self):
        if self.env.user.has_group('samalink_security_groups.group_samalink_hr_officer') or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        if not employee:
            raise AccessError(_("Your user is not linked to an employee record."))
        for rec in self:
            if rec.appraisal_id.state != 'published':
                raise AccessError(_("Manager feedback is allowed only in Published state."))
            if rec.manager_employee_id != employee:
                raise AccessError(_("You can edit only your own manager feedback."))
