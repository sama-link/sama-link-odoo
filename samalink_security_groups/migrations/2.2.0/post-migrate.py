"""Post-migration script for v2.2.0

Decouples Coach Manager from General Manager:
- Removes group_sl_coach_manager from users who got it via General Manager implies
  (only if they are not actually set as coach_id on any employee)
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("=== Migration 2.2.0: Decoupling Coach from General Manager ===")

    try:
        coach_group = env.ref('samalink_security_groups.group_sl_coach_manager')
        general_group = env.ref('samalink_security_groups.group_sl_general_manager')
    except ValueError:
        _logger.warning("Groups not found, skipping.")
        return

    Employee = env['hr.employee'].sudo()

    # For each user in Coach Manager group, check if they are actually a coach
    for user in coach_group.users:
        manager_employee = Employee.search([('user_id', '=', user.id)], limit=1)
        if manager_employee:
            is_coach = Employee.search_count([('coach_id', '=', manager_employee.id)]) > 0
        else:
            is_coach = False

        if not is_coach and user.id not in general_group.users.ids:
            # Not a coach and not a General Manager → remove Coach group
            _logger.info("Removing Coach Manager from user '%s' (not a coach for any employee)", user.name)
            coach_group.sudo().write({'users': [(3, user.id)]})

    _logger.info("=== Migration 2.2.0 complete ===")
