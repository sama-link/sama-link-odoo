from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


CATEGORY_SELECTION = [
    ('service', 'Service'),
    ('sales', 'Sales'),
    ('sales_online', 'Sales Online'),
    ('sales_projects', 'Sales Projects'),
    ('stock', 'Stock Purchasing'),
    ('installation', 'Installation'),
    ('branch_manager', 'Branch / Area Manager'),
    ('none', 'No Monthly Bonus'),
]

# Categories that pay with the Sales formula (per-employee target + commission
# tiers on collected sales). Keep in sync with the _calc_* aliases on the
# calculator and the sales-only columns of the batch XLSX export.
SALES_CATEGORIES = ('sales', 'sales_online', 'sales_projects')

# Each sales-flavoured category has its own manager group. Membership grants
# that category's data only: batch lines, targets, staging rows, CSV imports.
MANAGER_CATEGORY_GROUPS = {
    'sales': 'sl_monthly_bonus.group_bonus_manager',
    'sales_online': 'sl_monthly_bonus.group_bonus_manager_online',
    'sales_projects': 'sl_monthly_bonus.group_bonus_manager_projects',
}


def managed_bonus_categories(user):
    """Categories this user manages through a category-manager group.

    HR Manager implies all three manager groups, so HR gets the full set —
    callers that must let HR through unconditionally should test the HR group
    first, as the CSV import wizard does.
    """
    return {cat for cat, xmlid in MANAGER_CATEGORY_GROUPS.items()
            if user.has_group(xmlid)}


class SlBonusCategoryMixin(models.AbstractModel):
    _name = 'sl.bonus.category.mixin'
    _description = 'Bonus Category Mixin'

    @api.model
    def get_category_selection(self):
        return CATEGORY_SELECTION
