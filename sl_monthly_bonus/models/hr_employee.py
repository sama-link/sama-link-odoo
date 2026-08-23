from odoo import models, fields, api, _

BONUS_EVALUATION_MODES = [
    ('appraisal', 'Depends on appraisal'),
    ('fixed', 'Fixed (skip appraisal %)'),
]


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    bonus_quarterly_exclusion = fields.Boolean(
        string='Quarterly Bonus (excluded from monthly)',
        default=False,
        help='If set, this employee is part of the seven department managers '
             'on the quarterly bonus track and is excluded from monthly bonus calculation.',
    )
    bonus_edara_mapping_ids = fields.One2many(
        'sl.bonus.edara.mapping', 'employee_id',
        string='Edara Mappings',
    )

    # ── Bonus eligibility (employee card → "Appraisal & Bonus" tab) ──
    bonus_eligible = fields.Boolean(
        string='Bonus',
        default=True,
        help='Uncheck to exclude this employee from monthly bonuses: they can '
             'no longer be added to a bonus batch and compute to 0 if already in one.',
    )
    bonus_evaluation_mode = fields.Selection(
        BONUS_EVALUATION_MODES,
        string='Bonus Evaluation',
        default='appraisal',
        help="'Fixed' puts the employee on the Evaluation Exceptions list "
             "(Bonus → Configuration): the appraisal % is skipped (treated as "
             "100%) in their bonus formula. The two stay in sync both ways.",
    )

    # ── Bonus eligibility ⇄ Evaluation Exceptions list sync ──────────
    @api.onchange('bonus_eligible')
    def _onchange_bonus_eligible(self):
        if not self.bonus_eligible:
            self.bonus_evaluation_mode = 'appraisal'

    @api.model
    def _normalize_bonus_eligibility_vals(self, vals):
        """An employee who cannot take a bonus has no evaluation mode either:
        reset it so re-enabling starts from the default."""
        if 'bonus_eligible' in vals and not vals['bonus_eligible']:
            vals['bonus_evaluation_mode'] = 'appraisal'
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_bonus_eligibility_vals(vals)
        employees = super().create(vals_list)
        employees._sync_bonus_evaluation_exception()
        return employees

    def write(self, vals):
        self._normalize_bonus_eligibility_vals(vals)
        res = super().write(vals)
        if 'bonus_eligible' in vals or 'bonus_evaluation_mode' in vals:
            self._sync_bonus_evaluation_exception()
        return res

    def _sync_bonus_evaluation_exception(self):
        """Mirror the employee-card setting into the Evaluation Exceptions
        list. ``sl.bonus.evaluation.exception`` does the reverse sync on
        create/write/unlink; the context flag stops the two from
        ping-ponging. sudo: the card may be edited by users without write
        access on the configuration list itself."""
        if self.env.context.get('skip_bonus_exception_sync'):
            return
        Exception_ = self.env['sl.bonus.evaluation.exception'].sudo().with_context(
            skip_bonus_exception_sync=True)
        listed = {
            rec.employee_id.id: rec
            for rec in Exception_.search([('employee_id', 'in', self.ids)])
        }
        to_create = []
        to_unlink = Exception_.browse()
        for employee in self:
            should_be_listed = (
                employee.bonus_eligible
                and employee.bonus_evaluation_mode == 'fixed'
            )
            entry = listed.get(employee.id)
            if should_be_listed and not entry:
                to_create.append({
                    'employee_id': employee.id,
                    'reason': _('Fixed bonus (set on the employee card)'),
                })
            elif entry and not should_be_listed:
                to_unlink |= entry
        if to_create:
            Exception_.create(to_create)
        if to_unlink:
            to_unlink.unlink()

    def _bonus_get_active_contract(self, on_date=None):
        """Return the hr.contract in force for this employee on a given date
        (defaults to today).

        Departed/archived employees keep their bonus rights: when no running
        contract covers the date (departure closes the contract, sometimes
        with a date_end before the bonus period end), fall back to the most
        recent open/closed contract that started on or before the date so
        the last known wage is used.
        """
        self.ensure_one()
        on_date = on_date or fields.Date.today()
        # active_test=False: archiving an employee archives their contracts
        # too — those must still be found for departed employees.
        Contract = self.env['hr.contract'].sudo().with_context(active_test=False)
        base_domain = [
            ('employee_id', '=', self.id),
            ('date_start', '<=', on_date),
        ]
        contract = Contract.search(base_domain + [
            ('state', '=', 'open'),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
        ], order='date_start desc', limit=1)
        if not contract:
            contract = Contract.search(base_domain + [
                ('state', 'in', ('open', 'close')),
            ], order='date_start desc', limit=1)
        return contract

    def _bonus_is_in_probation(self, period_date_to):
        """Return True if employee is in probation on/after period_date_to."""
        self.ensure_one()
        contract = self._bonus_get_active_contract(on_date=period_date_to)
        if not contract:
            return False
        if contract.trial_date_end and contract.trial_date_end >= period_date_to:
            return True
        return False
