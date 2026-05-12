# -*- coding: utf-8 -*-
"""One-time data repair: link attachment res_model/res_id from M2M tables."""


def post_init_hook(cr, registry):
    """Fix legacy rows where binary widget left res_model/res_id empty."""
    from odoo import api

    su_id = getattr(api, 'SUPERUSER_ID', 2)
    env = api.Environment(cr, su_id, {})
    docs = env['hr.employee.document'].sudo().search([])
    if docs:
        docs._normalize_attachment_access_metadata()
    templates = env['hr.document'].sudo().search([])
    if templates:
        templates._normalize_attachment_access_metadata()
