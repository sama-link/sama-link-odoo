import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Menus the Sales Manager role is meant to reach. Only the leaves are listed:
# menuitems_whitelist walks each entry up to the root, so the parents (Monthly
# Bonus, Edara Data, Configuration) come along automatically.
SALES_MANAGER_MENUS = [
    'sl_monthly_bonus.menu_sl_bonus_lines_main',
    'sl_monthly_bonus.menu_sl_bonus_batches',
    'sl_monthly_bonus.menu_sl_bonus_edara_staging_sales',
    'sl_monthly_bonus.menu_sl_bonus_edara_import',
    'sl_monthly_bonus.menu_sl_bonus_config_target',
]


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _sl_bonus_sync_sales_manager_menus(self):
        """Whitelist the Sales Manager's menus for menuitems_whitelist.

        That module replaces menu visibility with a per-group whitelist
        (traversal_as='ancestors'): a group with an empty whitelist sees no
        menu at all, whatever the menuitem's own groups say. So the groups=
        attribute alone leaves this role staring at an empty app. Where the
        module is absent the field does not exist and there is nothing to do -
        hence the guard rather than a dependency, since the whitelist is a
        deployment choice and not something this module owns.
        """
        if 'whitelisted_menu_ids' not in self._fields:
            return
        group = self.env.ref(
            'sl_monthly_bonus.group_bonus_manager', raise_if_not_found=False)
        if not group:
            return
        menu_ids = []
        for xmlid in SALES_MANAGER_MENUS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                menu_ids.append(menu.id)
        if not menu_ids:
            return
        # Add, never replace: whatever else was granted by hand stays.
        group.sudo().write(
            {'whitelisted_menu_ids': [(4, menu_id) for menu_id in menu_ids]})
        # _visible_menu_ids is ormcached per group set.
        self.env.registry.clear_cache()
        _logger.info(
            "sl_monthly_bonus: whitelisted %d menus for the Sales Manager.",
            len(menu_ids))
