"""Install/upgrade hooks for samalink_hr."""


def post_init_hook(cr, registry):
    """Deactivate hr_custody employee view if the field is missing (orphaned UI).

    If ``hr_custody`` was uninstalled or is not on the server path but the view
    ``hr_custody.view_employee_form_custody`` remains in the database, opening
    the employee form raises: ``hr.employee.custody_count field is undefined``.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'custody_count' in env['hr.employee']._fields:
        return

    data = env['ir.model.data'].sudo().search([
        ('module', '=', 'hr_custody'),
        ('name', '=', 'view_employee_form_custody'),
        ('model', '=', 'ir.ui.view'),
    ])
    for rec in data:
        view = env['ir.ui.view'].sudo().browse(rec.res_id).exists()
        if view:
            view.write({'active': False})

    if not data:
        env['ir.ui.view'].sudo().search([
            ('model', '=', 'hr.employee'),
            ('name', '=', 'hr.employee.form.custody'),
            ('active', '=', True),
        ]).write({'active': False})
