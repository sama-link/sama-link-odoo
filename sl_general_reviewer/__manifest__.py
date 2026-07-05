{
    'name': 'Samalink General Reviewer',
    'version': '18.0.1.0.0',
    'summary': 'General Reviewer Manager group: read access to every model and every record',
    'description': """
Adds the "General Reviewer Manager" security group.

Members can READ every model and every record in the system: model ACLs and
record rules (including multi-company rules) are bypassed for READ operations
only. The group grants no write/create/delete rights by itself; a member's
write ability remains whatever their other groups grant.

Menu visibility: the group whitelists every menu item (menuitems_whitelist
gate, traversal 'ancestors') and is appended to the native groups of every
group-restricted menu, so reviewers can navigate the whole backend. Newly
created menus are picked up automatically.

Limitations: field-level groups= restrictions are a separate mechanism and
stay in force; debug mode stays gated by restrict_debug.
""",
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Tools',
    'depends': [
        'base',
        'menuitems_whitelist',        # whitelisted_menu_ids / traversal_as on res.groups
        'samalink_security_groups',   # reuse the "SamaLink" ir.module.category
    ],
    'data': [
        'security/sl_general_reviewer_groups.xml',
        'data/sl_general_reviewer_data.xml',   # <function>: must load AFTER the group
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
