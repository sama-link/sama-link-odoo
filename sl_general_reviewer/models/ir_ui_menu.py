import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

REVIEWER_GROUP = 'sl_general_reviewer.group_general_reviewer_manager'

# Root menus whose WHOLE subtree must stay hidden from reviewers: they are
# neither whitelisted nor joined via groups_id. Missing xmlids (module not
# installed) are skipped silently.
EXCLUDED_ROOT_MENU_XMLIDS = (
    'base.menu_management',       # Apps
    'base.menu_administration',   # Settings
    'survey.menu_surveys',        # Surveys
)


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _sl_reviewer_group(self):
        """The reviewer group, or None during uninstall / partial states."""
        return self.env.ref(REVIEWER_GROUP, raise_if_not_found=False)

    @api.model
    def _sl_reviewer_excluded_menu_ids(self):
        """Ids of every menu inside the excluded subtrees."""
        root_ids = []
        for xmlid in EXCLUDED_ROOT_MENU_XMLIDS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                root_ids.append(menu.id)
        if not root_ids:
            return set()
        return set(self.sudo().with_context(**{
            'ir.ui.menu.full_list': True,
            'active_test': False,
        }).search([('id', 'child_of', root_ids)]).ids)

    @api.model
    def _sl_reviewer_sync_menus(self):
        """Idempotent full re-seed, called by the data <function> tag on
        install and every upgrade.

        1. Whitelist every menu EXCEPT the excluded subtrees on the reviewer
           group (menuitems_whitelist; 'ancestors' traversal only includes
           whitelisted menus and their parents, so leaves must be
           whitelisted too).
        2. Append the group to groups_id of every non-excluded menu that
           ALREADY has a group restriction (native gate in core
           _visible_menu_ids). Menus with empty groups_id are NEVER
           touched: adding any group to an unrestricted menu would restrict
           it for everyone else.
        3. Remove the group from excluded menus it was joined to by earlier
           versions of the sync.
        """
        group = self._sl_reviewer_group()
        if not group:
            return
        menus = self.sudo().with_context(**{
            'ir.ui.menu.full_list': True,
            'active_test': False,
        }).search([])
        excluded_ids = self._sl_reviewer_excluded_menu_ids()
        allowed = menus.filtered(lambda m: m.id not in excluded_ids)
        group.sudo().write({'whitelisted_menu_ids': [(6, 0, allowed.ids)]})
        restricted = allowed.filtered(
            lambda m: m.groups_id and group not in m.groups_id)
        if restricted:
            restricted.write({'groups_id': [(4, group.id)]})
        leftover = (menus - allowed).filtered(lambda m: group in m.groups_id)
        if leftover:
            leftover.write({'groups_id': [(3, group.id)]})
        self.env.registry.clear_cache()
        _logger.info(
            "sl_general_reviewer: synced %d menus onto reviewer whitelist "
            "(%d restricted menus opened, %d excluded, %d cleaned up).",
            len(allowed), len(restricted), len(excluded_ids), len(leftover))

    @api.model_create_multi
    def create(self, vals_list):
        menus = super().create(vals_list)
        group = self._sl_reviewer_group()
        if group and menus:
            excluded_ids = self._sl_reviewer_excluded_menu_ids()
            wl = menus.filtered(lambda m: m.id not in excluded_ids)
            if wl:
                group.sudo().write(
                    {'whitelisted_menu_ids': [(4, menu.id) for menu in wl]})
                restricted = wl.filtered(
                    lambda m: m.groups_id and group not in m.groups_id)
                if restricted:
                    restricted.sudo().write({'groups_id': [(4, group.id)]})
            self.env.registry.clear_cache()
        return menus

    def write(self, values):
        res = super().write(values)
        if 'groups_id' in values:
            # Re-assert the invariant if a (6,0,...) write from module data
            # replaced the groups of a restricted menu. Excluded menus are
            # skipped, which also keeps the sync's cleanup writes from
            # re-triggering a join. Recursion is bounded: the inner write
            # adds the group, so the second pass filters to an empty set.
            group = self._sl_reviewer_group()
            if group:
                excluded_ids = self._sl_reviewer_excluded_menu_ids()
                restricted = self.filtered(
                    lambda m: m.id not in excluded_ids
                    and m.groups_id and group not in m.groups_id)
                if restricted:
                    restricted.sudo().write({'groups_id': [(4, group.id)]})
                self.env.registry.clear_cache()
        return res
