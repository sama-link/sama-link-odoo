import logging
from odoo import api, fields, models, tools

_logger = logging.getLogger(__name__)

class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _get_descendants(self, visible_menu_ids, whitelisted_menus):
        whitelisted_menu_ids = whitelisted_menus.ids
        visible_menus = self.browse(visible_menu_ids)

        for menu in visible_menus:
            while menu and menu.parent_id.id in whitelisted_menu_ids and menu.id not in whitelisted_menu_ids:
                whitelisted_menu_ids.append(menu.id)
                menu = menu.parent_id
        return whitelisted_menu_ids

    @api.model
    def _get_ancestors(self, whitelisted_menus):
        """Return the root menu ids of the whitelisted menus."""
        menu_ids = set()
        for menu in whitelisted_menus:
            while menu:
                menu_ids.add(menu.id)
                menu = menu.parent_id
        return menu_ids

    @api.model
    @tools.ormcache("frozenset(self.env.user.groups_id.ids)", "debug")
    def _visible_menu_ids(self, debug=False):
        """Return the ids of the menu items visible to the user."""
        visible_menu_ids = super()._visible_menu_ids(debug=debug)
        user_groups = self.env.user.groups_id
        grouped_groups = user_groups.grouped(lambda group: group.traversal_as)
        if not self.env.user.has_group("base.group_system"):
            # If the user is not a system user, filter visible menus based on group traversal
            descendants = grouped_groups.get("descendants")
            ancestors = grouped_groups.get("ancestors")
            if descendants:
                # If traversal_as is descendants, get all descendants of visible menus
                all_menu_ids = self._get_descendants(visible_menu_ids, descendants.mapped("whitelisted_menu_ids"))
            if ancestors:
                # If traversal_as is ancestors, get all ancestors of visible menus
                all_menu_ids = self._get_ancestors(ancestors.mapped("whitelisted_menu_ids"))
            return set(all_menu_ids) & visible_menu_ids
        else:
            return visible_menu_ids
