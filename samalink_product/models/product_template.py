from odoo import models, fields, api
from odoo.exceptions import ValidationError

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    part_number = fields.Char(string='Part Number')

    @api.constrains('part_number')
    def _check_part_number(self):
        for record in self:
            if record.part_number:
                existing_record = self.env['product.template'].search_count([('part_number', '=', record.part_number), ('id', '!=', record.id)])
                if existing_record > 0:
                    raise ValidationError(f"Part Number '{record.part_number}' must be unique.")