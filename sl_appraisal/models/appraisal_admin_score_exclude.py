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
        # admin_score and its breakdown are non-stored — invalidate so they
        # recompute on next read; total_score is stored, so recompute it now
        # (skipping records the administrator has manually overridden).
        appraisals.invalidate_recordset([
            'admin_score', 'admin_score_exempt',
            'weighted_admin_score', 'base_score',
        ])
        appraisals.filtered(
            lambda a: not a.total_score_manual_override
        )._compute_total_score()

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
