import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.quote_price import CABINET_SERIES, checked_number
from .workflow import ADMIN, internal_change, require_role


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nodo_cabinet_series = fields.Selection(CABINET_SERIES, string='单柜系列', index=True)
    nodo_cabinet_model = fields.Char(string='原报价型号')
    nodo_cabinet_variant = fields.Char(string='原报价变体', help='例如 JC 豪华型 LUXURY 或标配型 STANDARD。')
    nodo_quote_accessory_name = fields.Char(string='原报价附件名称', index=True)
    nodo_quote_accessory_category = fields.Char(string='原报价附件分类')

    @api.model
    def _nodo_catalog_fields(self):
        return {
            'nodo_cabinet_series', 'nodo_cabinet_model', 'nodo_cabinet_variant',
            'nodo_quote_accessory_name', 'nodo_quote_accessory_category',
        }

    @api.model_create_multi
    def create(self, vals_list):
        protected = self._nodo_catalog_fields()
        if any(set(vals) & protected for vals in vals_list) or any(
            self.env.context.get('default_' + field) for field in protected
        ):
            require_role(self.env, ADMIN)
        return super().create(vals_list)

    def write(self, vals):
        if self._nodo_catalog_fields() & vals.keys():
            require_role(self.env, ADMIN)
        return super().write(vals)


class SelectionAttachment(models.Model):
    _name = 'nodo.contract.selection.attachment'
    _description = '单柜报价附件'
    _check_company_auto = True
    _order = 'id'

    line_id = fields.Many2one('sale.order.line', string='选型行', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one(related='line_id.company_id', store=True, index=True)
    product_id = fields.Many2one('product.product', string='附件', required=True, check_company=True,
                                 domain="[('product_tmpl_id.nodo_quote_accessory_name', '!=', False)]")
    quantity = fields.Float(string='每台用量', required=True, default=1)
    quantity_pending = fields.Boolean(string='待填每台用量')
    selected = fields.Boolean(string='计入报价', default=True)
    model_code = fields.Char(string='附件型号')
    actual_dimensions = fields.Text(string='实测尺寸', help='填写原规则参数名和值，例如 {"长度": 600}。尺寸单位为毫米。')

    def _nodo_dimensions(self):
        self.ensure_one()
        try:
            values = json.loads(self.actual_dimensions) if self.actual_dimensions else {}
        except ValueError:
            raise ValidationError('附件实测尺寸需使用参数名与数值，例如 {"长度": 600}。') from None
        if not isinstance(values, dict) or any(
            not name.strip() or not checked_number(value) or value <= 0 for name, value in values.items()
        ):
            raise ValidationError('附件的实测尺寸须为有效正数。')
        return values

    @api.constrains('quantity', 'product_id', 'actual_dimensions', 'line_id')
    def _check_nodo_attachment(self):
        for attachment in self:
            if not attachment.line_id.order_id.nodo_contract or not attachment.product_id.nodo_quote_accessory_name:
                raise ValidationError('请选择已建立原报价映射的附件。')
            if not checked_number(attachment.quantity) or attachment.quantity <= 0:
                raise ValidationError('每台附件用量须大于零。')
            attachment._nodo_dimensions()

    def _nodo_allocation(self):
        self.ensure_one()
        if self.selected and self.quantity_pending:
            raise ValidationError(f'请填写附件「{self.product_id.nodo_quote_accessory_name}」的每台用量。')
        return {
            'name': self.product_id.nodo_quote_accessory_name,
            'category_level1': self.product_id.nodo_quote_accessory_category or '',
            'quantity': self.quantity, 'model_code': self.model_code or '',
            'selected': self.selected, 'manual_inputs': self._nodo_dimensions(),
            'scope': 'cabinet', 'cabinet_index': 0,
        }

    @api.model_create_multi
    def create(self, vals_list):
        line_ids = {vals.get('line_id') or self.env.context.get('default_line_id') for vals in vals_list}
        lines = self.env['sale.order.line'].browse([line_id for line_id in line_ids if line_id]).exists()
        if set(lines.ids) != line_ids:
            raise ValidationError('请先保存选型行。')
        lines.check_access('write')
        lines.order_id._nodo_check_selection_edit()
        return super().create(vals_list)

    def write(self, vals):
        if 'line_id' in vals:
            raise AccessError('请在对应选型行添加附件。')
        self.line_id.order_id._nodo_check_selection_edit()
        return super().write(vals)

    def unlink(self):
        if not internal_change():
            self.line_id.order_id._nodo_check_selection_edit()
        return super().unlink()
