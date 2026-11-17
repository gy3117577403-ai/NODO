from odoo import api, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

from .purchase_order import without_other_defaults


LINE_DRAFT_FIELDS = frozenset({
    'sequence', 'product_id', 'name', 'product_qty', 'uom_id', 'date_planned',
    'price_unit', 'technical_price_unit', 'discount', 'tax_ids', 'display_type',
})
SPEC_FIELDS = frozenset({'product_id', 'name', 'product_qty', 'uom_id', 'date_planned'})


class PurchaseOrderLine(models.Model):
    _name = 'purchase.order.line'
    _inherit = ['purchase.order.line', 'nodo.purchase.price.guard']

    _nodo_price_fields = frozenset({
        'discount', 'price_unit', 'technical_price_unit', 'price_unit_product_uom',
        'price_unit_discounted', 'price_subtotal', 'price_subtotal_to_invoice',
        'price_total', 'price_tax', 'non_deductible_tax', 'amount_to_invoice_at_date',
    })

    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if self.env.su or not self.env.user._is_internal():
            return domain
        order_operation = 'read' if operation == 'read' else 'write'
        return domain & Domain('order_id', 'any', self.env['purchase.order']._access_domain(order_operation))

    @api.model
    def _nodo_line_draft_values(self, vals, allowed_fields):
        if vals.keys() - allowed_fields:
            raise AccessError('只能修改采购草稿的物料、规格、数量和交期等明细。')
        for field_name in self._nodo_price_fields & vals.keys():
            self.check_field_access(self._fields[field_name], 'write')
        if vals.get('product_id'):
            self.env['product.product'].browse(vals['product_id']).check_access('read')

    @api.model_create_multi
    def create(self, vals_list):
        order_model = self.env['purchase.order']
        if not order_model._nodo_purchase_controlled():
            lines = super().create(vals_list)
            lines.order_id._nodo_clear_review()
            return lines
        allowed_fields = LINE_DRAFT_FIELDS | {'order_id'}
        can_price = self.env.user._nodo_purchase_permission_values()['price']
        if not can_price:
            allowed_fields -= self._nodo_price_fields | {'tax_ids'}
        line_model = without_other_defaults(self, {'order_id'})
        default_order_id = line_model.env.context.get('default_order_id')
        values = [{**vals, 'order_id': vals.get('order_id') or default_order_id} for vals in vals_list]
        for vals in values:
            self._nodo_line_draft_values(vals, allowed_fields)
        orders = order_model.browse({vals['order_id'] for vals in values if vals['order_id']})
        orders._nodo_require_purchase_action('draft', '你没有录入采购草稿的权限。')
        orders.check_access('write')
        # Native supplier price and tax recomputation stays on the server. A
        # price-blind user supplies only the checked non-price fields above.
        lines = super(PurchaseOrderLine, line_model.sudo(not can_price)).create(values)
        orders._nodo_clear_review()
        return lines.with_env(self.env)

    def write(self, vals):
        order_model = self.env['purchase.order']
        lines = self
        if vals and order_model._nodo_purchase_controlled():
            can_price = self.env.user._nodo_purchase_permission_values()['price']
            allowed_fields = LINE_DRAFT_FIELDS if can_price else LINE_DRAFT_FIELDS - self._nodo_price_fields - {'tax_ids'}
            self._nodo_line_draft_values(vals, allowed_fields)
            self.check_access('write')
            lines = self.sudo(not can_price)
        result = super(PurchaseOrderLine, lines).write(vals)
        if vals.keys() & SPEC_FIELDS:
            lines.sudo().order_id._nodo_clear_review()
        return result

    def unlink(self):
        orders = self.sudo().order_id
        result = super().unlink()
        orders._nodo_clear_review()
        return result

    @api.depends('name', 'order_id.name', 'price_unit_discounted')
    @api.depends_context('formatted_display_name', 'display_order_name', 'uid')
    def _compute_display_name(self):
        if self.env.context.get('display_order_name') and not self.has_field_access(self._fields['price_unit'], 'read'):
            for line in self:
                line.display_name = line.order_id.name
            return
        super()._compute_display_name()
