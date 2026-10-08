from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    as400_material_code = fields.Char(
        string='AS400 Material Code', index=True, copy=False,
        help='Material code used by AS400 to identify this product. '
             'If left empty, the Internal Reference and Barcode are used as a fallback '
             'when matching an inbound AS400 call to a product.')

    _sql_constraints = [
        ('as400_material_code_uniq', 'unique(as400_material_code)',
         'This AS400 Material Code is already assigned to another product.'),
    ]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    as400_material_code = fields.Char(
        string='AS400 Material Code',
        related='product_variant_ids.as400_material_code', readonly=False,
        help='Material code used by AS400 to identify this product '
             '(editable here only when the product has a single variant).')
