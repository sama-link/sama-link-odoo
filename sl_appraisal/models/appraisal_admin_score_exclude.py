from odoo import api, fields, models


class AppraisalAdminScoreExclude(models.Model):
    _name = 'appraisal.admin.score.exclude'
    _description = 'Appraisal Administration Score Exclusion'
    _rec_name = 'employee_id'
    _order = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        help="Employees listed here always receive an Administration Score of "
             "100%, regardless of absences, lateness, penalties, etc.",
    )

    _sql_constraints = [
        ('employee_uniq', 'unique(employee_id)',
         'This employee is already in the administrative exclusion list.'),
    ]

    def _recompute_related_appraisals(self, employees):
        """Refresh administration/total scores for the given employees'
        appraisals so excluded employees jump to (or back from) 100%."""
        if not employees:
            return
        appraisals = self.env['hr.appraisal'].sudo().search([
            ('employee_id', 'in', employees.ids),
        ])
        if not appraisals:
            return
        # The exclusion list is not part of any @api.depends chain, so the ORM
        # never learns the scores are stale. admin_score and base_score are
        # non-stored (they recompute on read), but total_score is stored: flag
        # base_score as modified so the ORM schedules total_score for
        # recomputation and flush. _compute_total_score itself skips records
        # the administrator has manually overridden.
        appraisals.invalidate_recordset([
            'admin_score', 'admin_score_exempt',
            'weighted_admin_score', 'base_score',
        ])
        appraisals.modified(['base_score'])

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._recompute_related_appraisals(records.employee_id)
        return records

    def write(self, vals):
        affected = self.employee_id
        res = super().write(vals)
        self._recompute_related_appraisals(affected | self.employee_id)
        return res

    def unlink(self):
        affected = self.employee_id
        res = super().unlink()
        self._recompute_related_appraisals(affected)
        return res
