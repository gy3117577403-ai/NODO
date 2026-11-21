from odoo import models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):
        standard_lines = self.filtered(lambda line: not line.order_id.nodo_contract)
        if not standard_lines:
            return True
        return super(SaleOrderLine, standard_lines)._action_launch_stock_rule(
            previous_product_uom_qty=previous_product_uom_qty,
        )
