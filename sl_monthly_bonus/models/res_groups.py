import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Menus each role must carry on its menuitems_whitelist entry. Only leaves are
# listed: that module walks every entry up to the root, so the parents (Monthly
# Bonus, Edara Data, Configuration, Data Import) come along automatically.
WHITELIST_GRANTS = {
    'sl_monthly_bonus.group_bonus_manager': [
        'sl_monthly_bonus.menu_sl_bonus_lines_main',
        'sl_monthly_bonus.menu_sl_bonus_batches',
        'sl_monthly_bonus.menu_sl_bonus_edara_staging_sales',
        'sl_monthly_bonus.menu_sl_bonus_config_target',
        'sl_monthly_bonus.menu_sl_bonus_csv_import',
    ],
    # Manual CSV Import is whitelisted for HR on the deployed databases but not
    # for Bonus / Administrator, which is why an admin could not see it however
    # the menuitem was declared. Listing it for both is idempotent.
    'sl_monthly_bonus.group_bonus_hr_manager': [
        'sl_monthly_bonus.menu_sl_bonus_csv_import',
    ],
    'sl_monthly_bonus.group_bonus_admin': [
        'sl_monthly_bonus.menu_sl_bonus_csv_import',
    ],
}

# Menus taken back from a role. Grants below are only ever added, so that
# entries made by hand survive an upgrade - which means a revocation has to be
# stated explicitly. v18.0.2.13.1 gave the Sales Manager the Edara CSV import;
# it was withdrawn and must go from databases that already received it.
WHITELIST_REVOKES = {
    'sl_monthly_bonus.group_bonus_manager': [
        'sl_monthly_bonus.menu_sl_bonus_edara_import',
    ],
}


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _sl_bonus_sync_menu_whitelist(self):
        """Keep the bonus roles' menuitems_whitelist entries in step.

        That module replaces menu visibility with a per-group whitelist
        (traversal_as='ancestors'): a group with no entry sees no menu at all,
        whatever the menuitem's own groups say. Where the module is absent the
        field does not exist and there is nothing to do - hence the guard
        rather than a dependency, since the whitelist is a deployment choice
        and not something this module owns.
        """
        if 'whitelisted_menu_ids' not in self._fields:
            return
        synced = 0
        for group_xmlid in set(WHITELIST_GRANTS) | set(WHITELIST_REVOKES):
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            if not group:
                continue
            commands = []
            for xmlid in WHITELIST_GRANTS.get(group_xmlid, ()):
                menu = self.env.ref(xmlid, raise_if_not_found=False)
                if menu:
                    commands.append((4, menu.id))
            for xmlid in WHITELIST_REVOKES.get(group_xmlid, ()):
                menu = self.env.ref(xmlid, raise_if_not_found=False)
                if menu:
                    commands.append((3, menu.id))
            if not commands:
                continue
            # Add and remove only what this module names: anything else granted
            # by hand on that group stays untouched.
            group.sudo().write({'whitelisted_menu_ids': commands})
            synced += 1
        # _visible_menu_ids is ormcached per group set.
        self.env.registry.clear_cache()
        _logger.info(
            "sl_monthly_bonus: synced the menu whitelist of %d groups.", synced)
