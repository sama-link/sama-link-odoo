import logging

_logger = logging.getLogger(__name__)

# Mapping: employee field → (group XML ID, field type)
MANAGER_FIELD_TO_GROUP = {
    'parent_id': ('samalink_security_groups.group_sl_general_manager', 'employee'),
    'coach_id': ('samalink_security_groups.group_sl_coach_manager', 'employee'),
    'leave_manager_id': ('samalink_security_groups.group_sl_timeoff_manager', 'user'),
    'attendance_manager_id': ('samalink_security_groups.group_sl_attendance_manager', 'user'),
}


def post_init_hook(cr, registry):
    """Sync existing employee manager fields → security groups on install/upgrade.
    
    For every employee that has parent_id, coach_id, leave_manager_id, or
    attendance_manager_id set, add the corresponding user to the matching
    security group if they are not already in it.
    """
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    Employee = env['hr.employee']
    Users = env['res.users']

    _logger.info("=== Syncing existing manager fields to security groups ===")

    for field_name, (group_xmlid, field_type) in MANAGER_FIELD_TO_GROUP.items():
        try:
            group = env.ref(group_xmlid)
        except ValueError:
            _logger.warning("Group %s not found, skipping sync.", group_xmlid)
            continue

        # Find all employees where this field is set
        employees = Employee.search([(field_name, '!=', False)])

        for emp in employees:
            manager_val = emp[field_name]
            if not manager_val:
                continue

            if field_type == 'user':
                user = manager_val  # already a res.users record
            else:
                user = manager_val.user_id  # hr.employee → user

            if user and user.exists() and user.id not in group.users.ids:
                _logger.info(
                    "Sync: Adding user '%s' to group '%s' (from employee '%s' field %s)",
                    user.name, group.name, emp.name, field_name,
                )
                group.sudo().write({'users': [(4, user.id)]})

    # Also migrate users from old group_samalink_manager to group_sl_general_manager
    try:
        old_group = env.ref('samalink_security_groups.group_samalink_manager')
        new_group = env.ref('samalink_security_groups.group_sl_general_manager')
        for user in old_group.users:
            if user.id not in new_group.users.ids:
                _logger.info(
                    "Sync: Migrating user '%s' from old Manager group to General Manager",
                    user.name,
                )
                new_group.sudo().write({'users': [(4, user.id)]})
        # Remove all users from old group
        old_group.sudo().write({'users': [(5,)]})
        _logger.info("Sync: Cleared old Manager (Legacy) group.")
    except ValueError:
        _logger.warning("Old Manager group not found, skipping migration.")

    _logger.info("=== Manager group sync complete ===")
