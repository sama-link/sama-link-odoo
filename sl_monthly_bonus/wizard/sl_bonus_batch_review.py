"""Wizard: review employees with a contract issue in the bonus period
before they are added to a bonus batch.

Opened from the Add Employees wizard (button "Review employees with
issues", or automatically when the chosen employees turn out to have
issues) and from the Add From Appraisal Batch wizard. One line per flagged
employee, showing why:

  * a contract starts or ends inside the bonus period (hired / departed /
    renewed mid-month) → HR decides add / don't add.
  (Unlike appraisal batches, a job change or a missing contract is not a
  bonus problem — departed employees keep their bonus rights.)

Employees WITHOUT issues that were selected alongside are carried in
``ok_employee_ids`` and always added on confirm. Line creation is delegated
to ``sl.bonus.batch._add_employees_to_lines`` so duplicate / state rules
apply identically to every entry point.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SlBonusBatchReview(models.TransientModel):
    _name = 'sl.bonus.batch.review'
    _description = 'Employees Needing Review Before Bonus'

    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Bonus Batch', required=True, ondelete='cascade',
    )
    period_start = fields.Date(related='batch_id.period_start', readonly=True)
    period_end = fields.Date(related='batch_id.period_end', readonly=True)
    ok_employee_ids = fields.Many2many(
        'hr.employee',
        'sl_bonus_review_ok_rel', 'wizard_id', 'employee_id',
        string='Employees Without Issues',
        context={'active_test': False},
        help='Selected employees with no issue in the period — always added '
             'when confirming.',
    )
    line_ids = fields.One2many(
        'sl.bonus.batch.review.line', 'wizard_id',
        string='Employees With Issues',
    )
    line_count = fields.Integer(compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)

    @api.model
    def _prepare_line_commands(self, batch, employees):
        """One2many create commands for every employee with a contract issue
        in the batch period. Employees without issues are left out."""
        issues = batch._employee_period_issues(employees)
        commands = []
        for employee in employees:
            issue = issues.get(employee.id)
            if not issue:
                continue
            commands.append((0, 0, {
                'employee_id': employee.id,
                'issue_summary': issue['summary'],
            }))
        return commands

    def action_confirm(self):
        self.ensure_one()
        batch = self.batch_id
        included = self.line_ids.filtered(lambda l: l.decision == 'include')
        employees = self.ok_employee_ids | included.mapped('employee_id')
        # Re-filter duplicates defensively (another user may have added
        # lines between the two wizard steps).
        employees -= batch.line_ids.mapped('employee_id')
        if not employees:
            raise UserError(_(
                "No employees left to add — everyone was either excluded "
                "or already has a line in this batch."
            ))
        created = batch._add_employees_to_lines(employees)

        excluded = self.line_ids.filtered(lambda l: l.decision == 'exclude')
        if excluded:
            # Plain text — message_post escapes HTML in interpolated bodies.
            batch.message_post(body=_(
                "Skipped %(count)s employee(s) after review of the period "
                "%(period_start)s → %(period_end)s: %(names)s"
            ) % {
                'count': len(excluded),
                'period_start': batch.period_start,
                'period_end': batch.period_end,
                'names': "، ".join(
                    "%s (%s)" % (l.employee_id.name, l.issue_summary)
                    for l in excluded),
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employees added'),
                'message': _(
                    "Added %(new)s new bonus line(s); %(skipped)s skipped after review."
                ) % {'new': len(created), 'skipped': len(excluded)},
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SlBonusBatchReviewLine(models.TransientModel):
    _name = 'sl.bonus.batch.review.line'
    _description = 'Employee Needing Review Before Bonus'
    _order = 'id'

    wizard_id = fields.Many2one(
        'sl.bonus.batch.review', required=True, ondelete='cascade',
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, readonly=True,
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Department', readonly=True,
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', string='Job Position', readonly=True,
    )
    issue_summary = fields.Char(
        string='Issue', readonly=True,
        help="Which contract starts / ends inside the bonus period.",
    )
    decision = fields.Selection([
        ('include', 'Add to Batch'),
        ('exclude', "Don't Add"),
    ], string='Decision', default='include', required=True)
