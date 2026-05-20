from odoo import models, fields, api, _


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

    def _bonus_get_active_contract(self, on_date=None):
        """Return active hr.contract for this employee on a given date (defaults to today)."""
        self.ensure_one()
        on_date = on_date or fields.Date.today()
        contract = self.env['hr.contract'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'open'),
            ('date_start', '<=', on_date),
            '|', ('date_end', '=', False), ('date_end', '>=', on_date),
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
