"""Reactivate the Edara Data menu.

The '🔄 Edara Data' parent menu was archived from the UI on production,
hiding the whole staging/sync section from everyone (including
administrators). Upgrades never touch the ``active`` flag, so it must be
restored explicitly. Only this menu is reactivated — other archived
bonus menus (Stock Commission, Audit Log, legacy self-service items...)
were hidden deliberately and stay as they are.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_ui_menu m
        SET active = TRUE
        FROM ir_model_data d
        WHERE d.model = 'ir.ui.menu'
          AND d.module = 'sl_monthly_bonus'
          AND d.name = 'menu_sl_bonus_edara'
          AND d.res_id = m.id
          AND m.active = FALSE
        """
    )
