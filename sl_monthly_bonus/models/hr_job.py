from odoo import models, fields, _
from .sl_bonus_category import CATEGORY_SELECTION


class HrJob(models.Model):
    _inherit = 'hr.job'

    bonus_category = fields.Selection(
        selection=CATEGORY_SELECTION,
        string='Bonus Category',
        default='none',
        help='Drives which bonus formula applies to employees holding this job position.\n'
             'Default is "No Monthly Bonus" — employees in jobs left at this default '
             'will receive 0 monthly bonus with a clear exclusion reason.\n'
             'Configure rate records under Bonus Configuration once you set a category.',
    )
