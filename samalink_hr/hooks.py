"""Install/upgrade hooks for samalink_hr."""


def _samalink_deactivate_orphan_custody_employee_views(env):
    """If ``custody_count`` is not on ``hr.employee``, disable views that reference it."""
    if 'custody_count' in env['hr.employee']._fields:
        return

    View = env['ir.ui.view'].sudo()
    to_disable = View.browse()

    data = env['ir.model.data'].sudo().search([
        ('module', '=', 'hr_custody'),
        ('name', '=', 'view_employee_form_custody'),
        ('model', '=', 'ir.ui.view'),
    ])
    to_disable |= View.browse(data.mapped('res_id')).exists()

    to_disable |= View.search([
        ('model', '=', 'hr.employee'),
        ('name', '=', 'hr.employee.form.custody'),
        ('active', '=', True),
    ])
    to_disable |= View.search([
        ('model', '=', 'hr.employee'),
        ('active', '=', True),
        ('arch_db', 'ilike', 'custody_count'),
    ])

    to_disable.write({'active': False})


def post_init_hook(cr, registry):
    """Deactivate hr_custody employee view if the field is missing (orphaned UI).

    If ``hr_custody`` was uninstalled or is not on the server path but the view
    ``hr_custody.view_employee_form_custody`` remains in the database, opening
    the employee form raises: ``hr.employee.custody_count field is undefined``.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    _samalink_deactivate_orphan_custody_employee_views(env)
