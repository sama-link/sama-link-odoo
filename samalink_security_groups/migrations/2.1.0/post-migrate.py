"""Post-migration script for v2.1.0

Runs once on upgrade from 2.0.0 → 2.1.0:
1. Strips the old 'Manager' group (noupdate=1, so XML can't touch it)
2. Syncs existing employee manager fields → security groups
3. Migrates old Manager users → General Manager
"""
import logging

_logger = logging.getLogger(__name__)

MANAGER_FIELD_TO_GROUP = {
    'parent_id': ('samalink_security_groups.group_sl_general_manager', 'employee'),
    'coach_id': ('samalink_security_groups.group_sl_coach_manager', 'employee'),
    'leave_manager_id': ('samalink_security_groups.group_sl_timeoff_manager', 'user'),
    'attendance_manager_id': ('samalink_security_groups.group_sl_attendance_manager', 'user'),
}


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("=== Migration 2.1.0: Syncing manager fields → security groups ===")

    # --- Step 1: Strip old Manager group (noupdate=1 blocks XML changes) ---
    try:
        old_group = env.ref('samalink_security_groups.group_samalink_manager')
        old_group.sudo().write({
            'name': 'Manager (Legacy)',
            'whitelisted_menu_ids': [(5,)],  # clear all
            'menu_access': [(5,)],           # clear all
        })
        _logger.info("Stripped old Manager group → 'Manager (Legacy)'")
    except ValueError:
        _logger.warning("Old Manager group not found, skipping.")

    # --- Step 2: Sync employee fields → security groups ---
    Employee = env['hr.employee']

    for field_name, (group_xmlid, field_type) in MANAGER_FIELD_TO_GROUP.items():
        try:
            group = env.ref(group_xmlid)
        except ValueError:
            _logger.warning("Group %s not found, skipping.", group_xmlid)
            continue

        employees = Employee.sudo().search([(field_name, '!=', False)])
        for emp in employees:
            manager_val = emp[field_name]
            if not manager_val:
                continue

            if field_type == 'user':
                user = manager_val
            else:
                user = manager_val.user_id

            if user and user.exists() and user.id not in group.users.ids:
                _logger.info(
                    "Sync: Adding '%s' to group '%s' (from employee '%s'.%s)",
                    user.name, group.name, emp.name, field_name,
                )
                group.sudo().write({'users': [(4, user.id)]})

    # --- Step 3: Migrate old Manager → General Manager ---
    try:
        old_group = env.ref('samalink_security_groups.group_samalink_manager')
        new_group = env.ref('samalink_security_groups.group_sl_general_manager')
        for user in old_group.users:
            if user.id not in new_group.users.ids:
                _logger.info("Migrating user '%s' from Manager → General Manager", user.name)
                new_group.sudo().write({'users': [(4, user.id)]})
        # Clear old group
        old_group.sudo().write({'users': [(5,)]})
        _logger.info("Cleared old Manager (Legacy) group users.")
    except ValueError:
        pass

    _logger.info("=== Migration 2.1.0 complete ===")
