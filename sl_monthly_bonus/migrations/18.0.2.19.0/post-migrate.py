"""Seed the new employee-card bonus eligibility fields.

``bonus_eligible`` / ``bonus_evaluation_mode`` were added to hr.employee in
18.0.2.19.0. Column creation already filled every existing employee with
the defaults (eligible / "Depends on appraisal"); this script aligns the
select with the existing Evaluation Exceptions list so employees already on
it show "Fixed" on their card.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    excepted = env['sl.bonus.evaluation.exception'].search([]).employee_id
    if excepted:
        excepted.with_context(
            active_test=False, skip_bonus_exception_sync=True,
        ).write({
            'bonus_eligible': True,
            'bonus_evaluation_mode': 'fixed',
        })
