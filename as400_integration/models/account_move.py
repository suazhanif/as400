from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    as400_synced = fields.Boolean(string='Sent to AS400', copy=False, readonly=True)
    as400_synced_date = fields.Datetime(string='AS400 Sync Date', copy=False, readonly=True)

    def _as400_build_payload(self):
        self.ensure_one()
        lines = []
        for line in self.invoice_line_ids.filtered(lambda l: l.display_type not in ('line_section', 'line_note')):
            lines.append({
                'product_code': line.product_id.as400_material_code
                                or line.product_id.default_code or '',
                'description': line.name,
                'quantity': line.quantity,
                'uom': line.product_uom_id.name,
                'unit_price': line.price_unit,
                'tax_amount': line.price_total - line.price_subtotal,
                'subtotal': line.price_subtotal,
                'total': line.price_total,
            })
        return {
            'invoice_reference': self.name,
            'invoice_date': fields.Date.to_string(self.invoice_date) if self.invoice_date else False,
            'customer_name': self.partner_id.name,
            'customer_reference': self.partner_id.ref or '',
            'currency': self.currency_id.name,
            'amount_untaxed': self.amount_untaxed,
            'amount_tax': self.amount_tax,
            'amount_total': self.amount_total,
            'lines': lines,
        }