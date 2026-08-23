"""Seed the new employee-card appraisal eligibility fields.

``appraisal_eligible`` / ``appraisal_admin_score_mode`` were added to
hr.employee in 18.0.1.4.0. Column creation already filled every existing
employee with the defaults (eligible / "Has administrative score"); this
script aligns the select with the existing Administrative Exclude list so
employees already on it show "No administrative score" on their card.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    excluded = env['appraisal.admin.score.exclude'].search([]).employee_id
    if excluded:
        excluded.with_context(
            active_test=False, skip_admin_exclude_sync=True,
        ).write({
            'appraisal_eligible': True,
            'appraisal_admin_score_mode': 'exempt',
        })
