"""Wizard: Add Employees From an Appraisal Batch.

Lets HR seed a bonus batch with the same employee population as an
existing ``hr.appraisal.batch``. The appraisal batch's state is not
relevant — the wizard reads its ``appraisal_ids`` and harvests each
appraisal's ``employee_id``. Appraisal data is never modified.

Duplicate prevention is delegated to
``sl.bonus.batch._add_employees_to_lines`` so the same rules apply as
when seeding directly.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SlBonusAddFromAppraisalWizard(models.TransientModel):
    _name = 'sl.bonus.add.from.appraisal.wizard'
    _description = 'Add Employees From an Appraisal Batch'

    batch_id = fields.Many2one(
        'sl.bonus.batch', string='Bonus Batch', required=True, ondelete='cascade',
    )
    company_id = fields.Many2one(related='batch_id.company_id', readonly=True)
    appraisal_batch_id = fields.Many2one(
        'hr.appraisal.batch', string='Appraisal Batch', required=True,
        domain="[('company_id', 'in', [company_id, False])]",
        help='Pick one appraisal batch — the wizard will add its '
             'employees to the bonus batch.',
    )
    candidate_count = fields.Integer(
        string='Employees in Appraisal Batch', compute='_compute_counts',
    )
    preview_count = fields.Integer(
        string='Will Add', compute='_compute_counts',
        help='Number of NEW lines this wizard will create after duplicate filtering.',
    )

    @api.depends('appraisal_batch_id', 'appraisal_batch_id.appraisal_ids',
                 'batch_id', 'batch_id.line_ids')
    def _compute_counts(self):
        for wiz in self:
            employees = wiz._candidate_employees()
            wiz.candidate_count = len(employees)
            existing_ids = (
                set(wiz.batch_id.line_ids.mapped('employee_id.id'))
                if wiz.batch_id else set()
            )
            wiz.preview_count = sum(
                1 for e in employees if e.id not in existing_ids
            )

    def _candidate_employees(self):
        """Distinct ``hr.employee`` recordset drawn from the selected
        appraisal batch's appraisals."""
        self.ensure_one()
        if not self.appraisal_batch_id:
            return self.env['hr.employee']
        # Appraised employees whose "Bonus" box is unchecked on the employee
        # card (Appraisal & Bonus tab) cannot take a bonus — leave them out.
        return self.appraisal_batch_id.sudo().appraisal_ids.mapped(
            'employee_id').filtered('bonus_eligible')

    def _bind_appraisal_batch(self):
        """Make the selected appraisal batch the bonus batch's official
        evaluation reference (subsequent compute runs use only the
        appraisals inside it — see sl.bonus.calculator). sudo: HR users may
        not have direct write on every bonus batch field, but they did just
        run the wizard, which already enforces HR/Admin via
        action_open_add_from_appraisal_wizard."""
        self.ensure_one()
        if not self.batch_id.appraisal_batch_id:
            self.batch_id.sudo().write({
                'appraisal_batch_id': self.appraisal_batch_id.id,
            })
            self.batch_id.message_post(body=_(
                "تم ربط دفعة المكافآت بدفعة التقييم: <b>%s</b>"
            ) % self.appraisal_batch_id.name)
        elif self.batch_id.appraisal_batch_id != self.appraisal_batch_id:
            # A different appraisal batch is already bound — refuse to
            # silently overwrite; HR clears the link first (draft/data_ready)
            # or opens the right one.
            raise UserError(_(
                "This bonus batch is already linked to a different appraisal "
                "batch ('%(old)s'). Clear that link first if you want to "
                "rebind it to '%(new)s'."
            ) % {
                'old': self.batch_id.appraisal_batch_id.name,
                'new': self.appraisal_batch_id.name,
            })

    def action_confirm(self):
        self.ensure_one()
        if not self.batch_id:
            raise UserError(_("No bonus batch selected."))
        if not self.appraisal_batch_id:
            raise UserError(_("Select an appraisal batch first."))
        # The eligibility / state gating for whether the batch can still
        # accept employees lives in ``sl.bonus.batch._add_employees_to_lines``;
        # we call that path so both wizards share the same rules.
        employees = self._candidate_employees()
        if not employees:
            raise UserError(_(
                "Appraisal batch '%s' has no appraisals — nothing to add."
            ) % self.appraisal_batch_id.name)
        self._bind_appraisal_batch()
        # Employees with a contract starting/ending in the bonus period (or
        # none at all) are decided one by one in the review wizard; the
        # others are carried along and added when it is confirmed.
        issues = self.batch_id._employee_period_issues(employees)
        flagged = employees.filtered(lambda e: e.id in issues)
        if flagged:
            return self.batch_id._open_review_wizard(flagged, employees - flagged)
        created = self.batch_id._add_employees_to_lines(employees)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Employees added'),
                'message': _(
                    "Added %(new)s new bonus line(s) from appraisal batch '%(name)s'; "
                    "%(skipped)s employee(s) were already present. This appraisal "
                    "batch is now the evaluation reference for the bonus batch."
                ) % {
                    'new': len(created),
                    'name': self.appraisal_batch_id.name,
                    'skipped': len(employees) - len(created),
                },
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
