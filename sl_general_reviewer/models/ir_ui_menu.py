import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

REVIEWER_GROUP = 'sl_general_reviewer.group_general_reviewer_manager'


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _sl_reviewer_group(self):
        """The reviewer group, or None during uninstall / partial states."""
        return self.env.ref(REVIEWER_GROUP, raise_if_not_found=False)

    @api.model
    def _sl_reviewer_sync_menus(self):
        """Idempotent full re-seed, called by the data <function> tag on
        install and every upgrade.

        1. Whitelist EVERY menu on the reviewer group (menuitems_whitelist;
           'ancestors' traversal only includes whitelisted menus and their
           parents, so leaves must be whitelisted too).
        2. Append the group to groups_id of every menu that ALREADY has a
           group restriction (native gate in core _visible_menu_ids).
           Menus with empty groups_id are NEVER touched: adding any group
           to an unrestricted menu would restrict it for everyone else.
        """
        group = self._sl_reviewer_group()
        if not group:
            return
        menus = self.sudo().with_context(**{
            'ir.ui.menu.full_list': True,
            'active_test': False,
        }).search([])
        group.sudo().write({'whitelisted_menu_ids': [(6, 0, menus.ids)]})
        restricted = menus.filtered(
            lambda m: m.groups_id and group not in m.groups_id)
        if restricted:
            restricted.write({'groups_id': [(4, group.id)]})
        self.env.registry.clear_cache()
        _logger.info(
            "sl_general_reviewer: synced %d menus onto reviewer whitelist "
            "(%d restricted menus opened).", len(menus), len(restricted))

    @api.model_create_multi
    def create(self, vals_list):
        menus = super().create(vals_list)
        group = self._sl_reviewer_group()
        if group and menus:
            group.sudo().write(
                {'whitelisted_menu_ids': [(4, menu.id) for menu in menus]})
            restricted = menus.filtered(
                lambda m: m.groups_id and group not in m.groups_id)
            if restricted:
                restricted.sudo().write({'groups_id': [(4, group.id)]})
            self.env.registry.clear_cache()
        return menus

    def write(self, values):
        res = super().write(values)
        if 'groups_id' in values:
            # Re-assert the invariant if a (6,0,...) write from module data
            # replaced the groups of a restricted menu. Recursion is bounded:
            # the inner write adds the group, so the second pass filters to
            # an empty set.
            group = self._sl_reviewer_group()
            if group:
                restricted = self.filtered(
                    lambda m: m.groups_id and group not in m.groups_id)
                if restricted:
                    restricted.sudo().write({'groups_id': [(4, group.id)]})
                self.env.registry.clear_cache()
        return res
