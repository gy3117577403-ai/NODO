from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from ..services.quote_price import COATINGS, DOORS, MATERIALS, allowed_doors, checked_number
from .workflow import APPROVAL, COSTING, COST_GROUPS, SALES, has_role, internal_change, workflow_change


SELECTION_FIELDS = {
    'order_id', 'sequence', 'name', 'product_id', 'product_template_id', 'product_uom_id', 'product_uom_qty',
    'tax_ids', 'analytic_distribution', 'display_type', 'nodo_width', 'nodo_depth', 'nodo_height',
    'nodo_base_height', 'nodo_thickness', 'nodo_material', 'nodo_coating', 'nodo_color', 'nodo_door',
    'nodo_attachments', 'nodo_customer_name', 'nodo_manual_remark', 'nodo_remark',
}
COST_EDIT_FIELDS = {
    'nodo_coefficient', 'nodo_freight_mode', 'nodo_freight', 'nodo_quote_freight_mode', 'nodo_quote_freight',
}
NATIVE_COST_FIELDS = {'margin', 'margin_percent', 'purchase_price'}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    nodo_cabinet_series = fields.Selection(related='product_id.nodo_cabinet_series', string='系列')
    nodo_width = fields.Float(string='宽（毫米）')
    nodo_depth = fields.Float(string='深（毫米）')
    nodo_height = fields.Float(string='高（毫米）')
    nodo_base_height = fields.Float(string='底座高度（毫米）')
    nodo_thickness = fields.Float(string='料厚（毫米）', default=1.5)
    nodo_material = fields.Selection(MATERIALS, string='材质', default='SECC')
    nodo_coating = fields.Selection(COATINGS, string='喷塑', default='orange')
    nodo_color = fields.Char(string='颜色', default='RAL7035 浅灰')
    nodo_door = fields.Selection([(key, value[0]) for key, value in DOORS.items()],
                                 string='门型', help='留空时按原报价的系列和宽度选择默认门型。')
    nodo_effective_door = fields.Char(compute='_compute_nodo_effective_door', string='实际门型')
    nodo_specification = fields.Char(compute='_compute_nodo_specification', string='规格（宽×深×高）')
    nodo_attachments = fields.One2many('nodo.contract.selection.attachment', 'line_id', string='柜体附件', copy=True)
    nodo_customer_name = fields.Char(string='对客名称', help='留空时沿用产品名称。')
    nodo_manual_remark = fields.Boolean(string='使用人工备注')
    nodo_remark = fields.Text(string='人工备注')
    nodo_generated_remark = fields.Text(string='原规则生成的备注', readonly=True, copy=False)
    nodo_coefficient = fields.Float(string='折扣系数', default=1, digits=(16, 6), groups=COST_GROUPS)
    nodo_freight_mode = fields.Selection([('AUTO', '自动'), ('MANUAL', '手填')],
                                         string='成本运费', default='AUTO', groups=COST_GROUPS)
    nodo_freight = fields.Float(string='单台成本运费', digits=(16, 2), groups=COST_GROUPS)
    nodo_quote_freight_mode = fields.Selection([('FOLLOW_COST', '随成本'), ('MANUAL', '手填')],
                                               string='对客运费', default='FOLLOW_COST', groups=COST_GROUPS)
    nodo_quote_freight = fields.Float(string='单台对客运费', digits=(16, 2), groups=COST_GROUPS)

    @api.model
    def _access_domain(self, operation):
        domain = super()._access_domain(operation)
        if self.env.su:
            return domain
        order_access = 'read' if operation == 'read' else 'write'
        return domain & (
            Domain('order_id.nodo_contract', '=', False) | Domain('order_id', 'access', order_access)
        )

    @api.model
    def has_field_access(self, field, operation):
        if field.name in NATIVE_COST_FIELDS and has_role(self.env, SALES) and not has_role(self.env, COSTING, APPROVAL):
            return False
        return super().has_field_access(field, operation)

    @api.model
    def check_field_access(self, field, operation):
        if field.name in NATIVE_COST_FIELDS and not self.has_field_access(field, operation):
            raise AccessError('当前岗位无权查看成本与利润。')
        return super().check_field_access(field, operation)

    @api.depends('nodo_width', 'nodo_depth', 'nodo_height')
    def _compute_nodo_specification(self):
        for line in self:
            line.nodo_specification = ' × '.join(f'{x:g}' for x in (line.nodo_width, line.nodo_depth, line.nodo_height)) if (
                line.nodo_width and line.nodo_depth and line.nodo_height
            ) else False

    @api.depends('product_id.nodo_cabinet_series', 'nodo_width', 'nodo_door')
    def _compute_nodo_effective_door(self):
        for line in self:
            line.nodo_effective_door = DOORS[line._nodo_effective_door()][0] if line.nodo_cabinet_series else False

    def _nodo_effective_door(self):
        self.ensure_one()
        options = allowed_doors(self.nodo_cabinet_series)
        return self.nodo_door or (options[1] if self.nodo_width > 800 and len(options) > 1 else options[0])

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'order_id.nodo_contract')
    def _compute_price_unit(self):
        managed = self.filtered(lambda line: line.order_id.nodo_contract)
        super(SaleOrderLine, self - managed)._compute_price_unit()
        with workflow_change():
            for line in managed:
                line.with_context(sale_write_from_compute=True).update({'price_unit': line.technical_price_unit})

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty', 'order_id.nodo_contract')
    def _compute_discount(self):
        managed = self.filtered(lambda line: line.order_id.nodo_contract)
        super(SaleOrderLine, self - managed)._compute_discount()
        managed.discount = 0

    @api.model_create_multi
    def create(self, vals_list):
        if not internal_change():
            for vals in vals_list:
                order_id = vals.get('order_id') or self.env.context.get('default_order_id')
                order = self.env['sale.order'].browse(order_id).exists()
                if order.nodo_contract:
                    order._nodo_check_selection_edit()
                    if vals.keys() - SELECTION_FIELDS or any(
                        key.startswith('default_') and key[8:] not in SELECTION_FIELDS | {'nodo_contract', 'company_id'}
                        for key in self.env.context
                    ):
                        raise AccessError('请在选型中填写单柜信息，金额由原报价服务回填。')
        return super().create(vals_list)

    def write(self, vals):
        if internal_change() or not vals:
            return super().write(vals)
        target = self.env['sale.order'].browse(vals.get('order_id')).exists()
        managed = self.filtered(lambda line: line.order_id.nodo_contract).order_id
        if 'order_id' in vals and (managed or target.nodo_contract):
            raise AccessError('报价明细归属原单据，请在对应报价添加产品。')
        if not managed:
            return super().write(vals)
        if vals.keys() <= SELECTION_FIELDS:
            managed._nodo_check_selection_edit()
        elif vals.keys() <= COST_EDIT_FIELDS:
            managed._nodo_check_cost_edit()
        else:
            raise AccessError('报价金额与历史结果由核算流程保存。')
        result = super().write(vals)
        if vals.keys() & COST_EDIT_FIELDS:
            managed._nodo_clear_price()
        return result

    def unlink(self):
        if not internal_change():
            self.filtered(lambda line: line.order_id.nodo_contract).order_id._nodo_check_selection_edit()
        return super().unlink()

    @api.constrains('product_id', 'nodo_door', 'nodo_width', 'nodo_depth', 'nodo_height', 'nodo_base_height',
                    'nodo_thickness', 'nodo_coefficient', 'nodo_freight', 'nodo_quote_freight')
    def _check_nodo_selection(self):
        for line in self.sudo().filtered(lambda record: record.order_id.nodo_contract and not record.display_type):
            if not line.product_id.nodo_cabinet_series or not line.product_id.sale_ok:
                raise ValidationError('请选择启用且已映射原价格目录的柜体产品。')
            if line.nodo_door and line.nodo_door not in allowed_doors(line.product_id.nodo_cabinet_series):
                raise ValidationError('当前门型不适用于此柜体系列。')
            values = [
                line.nodo_width, line.nodo_depth, line.nodo_height, line.nodo_thickness, line.nodo_base_height,
                line.nodo_coefficient, line.nodo_freight, line.nodo_quote_freight,
            ]
            if not all(checked_number(value) and value >= 0 for value in values):
                raise ValidationError('规格、系数和运费须为有效非负数。')

    def _nodo_pricing_row(self):
        self.ensure_one()
        line = self.sudo()
        product = line.product_id
        series = product.nodo_cabinet_series
        if not series or not product.active or not product.sale_ok:
            raise ValidationError('请选择有效的单柜产品及原价格目录映射。')
        qty = line.product_uom_qty
        if not checked_number(qty) or qty <= 0 or qty != int(qty):
            raise ValidationError('单柜数量按台计，须为正整数。')
        if line.product_uom_id != product.uom_id:
            raise ValidationError('单柜报价须使用柜体产品的基础计量单位。')
        if not all(checked_number(value) and value > 0 for value in (
            line.nodo_width, line.nodo_depth, line.nodo_height, line.nodo_thickness,
        )) or not line.nodo_material or not line.nodo_coating:
            raise ValidationError(f'请填写 {product.name} 的宽、深、高、料厚、材质和喷塑。')
        door = line._nodo_effective_door()
        if door not in allowed_doors(series):
            raise ValidationError('当前门型不适用于此柜体系列。')
        return {
            'line': line.id, 'product': product.id, 'series': series, 'door': door,
            'name': line.nodo_customer_name or product.name,
            'model': product.nodo_cabinet_model or product.default_code or '',
            'variant': product.nodo_cabinet_variant or '',
            'width': line.nodo_width, 'depth': line.nodo_depth, 'height': line.nodo_height,
            'specification': line.nodo_specification,
            'quantity': qty, 'unit': line.product_uom_id.display_name,
            'material': line.nodo_material, 'thickness': line.nodo_thickness, 'base_height': line.nodo_base_height,
            'coating': line.nodo_coating, 'color': line.nodo_color or '',
            'coefficient': line.nodo_coefficient,
            'date': fields.Date.to_string(fields.Date.context_today(self)),
            'freight_mode': line.nodo_freight_mode, 'freight': line.nodo_freight,
            'quote_freight_mode': line.nodo_quote_freight_mode, 'quote_freight': line.nodo_quote_freight,
            'manual_remark': line.nodo_manual_remark, 'remark': line.nodo_remark or '',
            'attachments': [attachment._nodo_allocation() for attachment in line.nodo_attachments],
        }

    def _nodo_customer_row(self):
        self.ensure_one()
        amount = self.price_total if self.order_id.document_tax_mode == 'tax_included' else self.price_subtotal
        unit_price = self.currency_id.round(amount / self.product_uom_qty)
        return {
            'name': self.nodo_customer_name or self.product_id.name, 'specification': self.nodo_specification,
            'quantity': self.product_uom_qty, 'unit': self.product_uom_id.display_name,
            'unit_price': unit_price, 'total': amount,
            'remark': (self.nodo_remark if self.nodo_manual_remark else self.nodo_generated_remark) or '',
        }
