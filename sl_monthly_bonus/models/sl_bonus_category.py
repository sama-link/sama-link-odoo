from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


CATEGORY_SELECTION = [
    ('service', 'Service'),
    ('sales', 'Sales'),
    ('stock', 'Stock Purchasing'),
    ('installation', 'Installation'),
    ('branch_manager', 'Branch / Area Manager'),
    ('none', 'No Monthly Bonus'),
]


class SlBonusCategoryMixin(models.AbstractModel):
    _name = 'sl.bonus.category.mixin'
    _description = 'Bonus Category Mixin'

    @api.model
    def get_category_selection(self):
        return CATEGORY_SELECTION
