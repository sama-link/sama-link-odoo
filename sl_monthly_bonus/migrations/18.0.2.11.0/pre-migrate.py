"""Drop dangling menu xmlids so deleted menus are recreated.

The 'Mapping' and 'Staging — Sales' menus were deleted from the UI on
production, but their ir.model.data rows survived (dangling xmlids
pointing at missing ir.ui.menu records). The ORM then skips those
menuitems on every upgrade instead of recreating them. Deleting the
dangling rows here lets this upgrade recreate the menus from XML.
"""


def migrate(cr, version):
    cr.execute(
        """
        DELETE FROM ir_model_data d
        WHERE d.module = 'sl_monthly_bonus'
          AND d.model = 'ir.ui.menu'
          AND NOT EXISTS (SELECT 1 FROM ir_ui_menu m WHERE m.id = d.res_id)
        """
    )
