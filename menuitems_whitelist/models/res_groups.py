from odoo import models, fields, api


class ResGroups(models.Model):
    _inherit = 'res.groups'

    traversal_as = fields.Selection(
        selection=[
            ('ancestors', 'Ancestors'),
            ('descendants', 'Descendants'),
        ],  string="Traversal As", default='ancestors',
        help="Defines how the menu items are traversed for this group. "
             "If 'Ancestors', choosen menus and their parent menus are included. "
             "If 'Descendants', choosen menus and their child menus are included."
    )
    whitelisted_menu_ids = fields.Many2many(
        comodel_name="ir.ui.menu",
        relation="res_groups_whitelist_menu_rel",
        column1="group_id",
        column2="menu_id",
        string="Whitelisted Menus",
        help="Root menu items that are whitelisted for this group."
    )

    @api.onchange('traversal_as')
    def _onchange_traversal_as(self):
        """Ensure that whitelisted_menu_ids is cleared when traversal_as changes."""
        if self.whitelisted_menu_ids.exists():
            self.whitelisted_menu_ids = False
            
            return {
                'warning': {
                    'title': "Traversal As Changed",
                    'message': "Whitelisted menus have been cleared due to change in traversal method."
                }
            }