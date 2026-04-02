"""Post-migration script for v2.3.0

Deletes the old Manager (Legacy) group from the database.
XML removal alone won't work because it was created under noupdate=1.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("=== Migration 2.3.0: Deleting Manager (Legacy) group ===")

    try:
        old_group = env.ref('samalink_security_groups.group_samalink_manager', raise_if_not_found=False)
        if old_group:
            # Remove all users first
            old_group.sudo().write({'users': [(5,)], 'implied_ids': [(5,)]})
            # Delete the model data reference
            model_data = env['ir.model.data'].sudo().search([
                ('module', '=', 'samalink_security_groups'),
                ('name', '=', 'group_samalink_manager'),
            ])
            # Delete the group
            old_group.sudo().unlink()
            _logger.info("Deleted Manager (Legacy) group from database.")
        else:
            _logger.info("Manager (Legacy) group already deleted.")
    except Exception as e:
        _logger.warning("Could not delete Manager (Legacy) group: %s", e)

    _logger.info("=== Migration 2.3.0 complete ===")
