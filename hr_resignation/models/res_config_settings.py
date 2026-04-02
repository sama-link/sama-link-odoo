# -*- coding: utf-8 -*-
from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hr_resignation_min_notice_period = fields.Integer(
        string="Minimum Notice Period (Days)",
        config_parameter='hr_resignation.min_notice_period',
        default=30,
        help="The minimum amount of days an employee must provide before their Last Day"
    )
