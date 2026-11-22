import json

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from ..services.drawing_selection import DOOR_KEYS, SELECTION_DEFAULTS, accessory_values, cabinet_values
from ..services.quote_price import COATINGS, MATERIALS, checked_number
from .workflow import workflow_change


class SaleSelection(models.Model):
    _inherit = 'sale.order'

    nodo_quote_drawing_ids = fields.One2many('nodo.contract.drawing', 'order_id', string='图纸与选型', copy=False)
    drawing_recognition_pending = fields.Boolean(compute='_compute_nodo_drawing_progress')
    drawing_recognition_version = fields.Char(compute='_compute_nodo_drawing_progress')

    @api.depends('nodo_quote_drawing_ids.drawing_recognition_version')
    def _compute_nodo_drawing_progress(self):
        for order in self:
            drawings = order.nodo_quote_drawing_ids
            order.drawing_recognition_pending = any(drawings.mapped('drawing_recognition_pending'))
            order.drawing_recognition_version = ';'.join(drawings.mapped('drawing_recognition_version'))

    @api.readonly
    def get_drawing_recognition_progress(self):
        self.ensure_one()
        self.check_access('read')
        return {'version': self.drawing_recognition_version}

    def _nodo_accessory_catalog(self):
        self.ensure_one()
        products = self.env['product.product'].search([
            ('active', '=', True), ('nodo_quote_accessory_name', '!=', False),
            ('company_id', 'in', [False, self.company_id.id]),
        ], order='name,id')
        catalog = {}
        for product in products:
            name = product.nodo_quote_accessory_name
            item = catalog.setdefault(name, {
                'name': name, 'category': product.nodo_quote_accessory_category or '附件',
                'product_ids': [], 'part_numbers': [],
            })
            item['product_ids'].append(product.id)
            if product.default_code:
                item['part_numbers'].append(product.default_code)
        return catalog

    def _nodo_drawing_line(self, drawing, candidate):
        self.ensure_one()
        if candidate:
            direct = self.order_line.filtered(lambda line: line.nodo_drawing_candidate_id == candidate)
            if direct:
                return direct[:1]
            previous = self.order_line.filtered(lambda line: (
                line.nodo_source_drawing_id == drawing and line.nodo_drawing_candidate_id
                and line.nodo_drawing_candidate_id.recognition_token != candidate.recognition_token
                and line.nodo_drawing_candidate_id.page_number == candidate.page_number
                and line.nodo_drawing_candidate_id.name == candidate.name
            ))
            return previous if len(previous) == 1 else self.env['sale.order.line']
        return drawing.order_line_id if not drawing.order_line_id.nodo_drawing_candidate_id else self.env['sale.order.line']

    @api.readonly
    def get_selection_table(self):
        self.ensure_one()
        self.check_access('read')
        if not self.nodo_contract:
            raise UserError('此报价使用原有销售明细。')
        used, rows = set(), []
        for drawing in self.nodo_quote_drawing_ids:
            current = drawing._current_candidates()
            for candidate in current:
                line = self._nodo_drawing_line(drawing, candidate)
                if drawing.active_recognition_id == candidate:
                    values = drawing._values()
                else:
                    values = candidate.review_values or candidate.suggested_values or {}
                row = {
                    **cabinet_values(values), 'key': f'candidate_{candidate.id}', 'source': 'drawing',
                    'drawing_id': drawing.id, 'candidate_id': candidate.id, 'page': candidate.page_number,
                    'line_id': line.id or False, 'product_id': line.product_id.id or False, 'state': candidate.review_state,
                    'placeholder': not values.get('product_series'), 'recognition_state': drawing.recognition_state,
                    'product_name': line.product_id.name or values.get('product_series') or '待选型',
                }
                if line and line.nodo_drawing_candidate_id == candidate:
                    used.add(line.id)
                rows.append(row)
            if not current and not drawing.selection_row_hidden:
                line = drawing.order_line_id
                if line:
                    used.add(line.id)
                rows.append({
                    **drawing._values(), 'key': f'drawing_{drawing.id}', 'source': 'drawing',
                    'drawing_id': drawing.id, 'candidate_id': False, 'line_id': line.id or False,
                    'product_id': line.product_id.id or False, 'state': drawing.state,
                    'placeholder': not drawing.product_series, 'recognition_state': drawing.recognition_state,
                    'product_name': line.product_id.name or drawing.product_series or '待选型',
                })
        rows.extend(line._nodo_selection_row() for line in self.order_line.sorted('sequence') if line.id not in used)
        return {
            'rows': rows,
            'attachments': [{'id': drawing.id, 'name': drawing.name, 'pages': drawing.page_count, 'kind': drawing.file_kind,
                             'recognition_state': drawing.recognition_state, 'error': drawing.recognition_error or ''}
                            for drawing in self.nodo_quote_drawing_ids],
            'drawing': bool(self.nodo_quote_drawing_ids), 'editable': self.nodo_can_edit_selection and not self.locked,
        }

    @api.readonly
    def get_selection_accessory_catalog(self):
        self.ensure_one()
        self.check_access('read')
        if not self.nodo_contract:
            raise UserError('请选择启用单柜选型的报价。')
        return list(self._nodo_accessory_catalog().values())

    def action_upload_drawing(self):
        self.ensure_one()
        self._nodo_check_selection_edit()
        if not self.nodo_quote_drawing_ids and self.order_line.filtered(lambda line: not line.display_type):
            raise UserError('当前报价包含无图纸产品。请新建报价，再上传图纸关联选型。')
        return {
            'name': '上传图纸', 'type': 'ir.actions.act_window', 'res_model': 'nodo.contract.drawing',
            'views': [(self.env.ref('nodo_contract.view_drawing_upload').id, 'form')], 'target': 'new',
            'context': {**self.env.context, 'default_order_id': self.id},
        }

    def _nodo_checked_drawing(self, drawing_id):
        drawing = self.nodo_quote_drawing_ids.filtered(lambda row: row.id == drawing_id)
        if not drawing:
            raise AccessError('图纸不属于当前报价。')
        return drawing

    def open_selection_row(self, drawing_id, candidate_id=0):
        self.ensure_one()
        self.check_access('read')
        drawing = self._nodo_checked_drawing(drawing_id)
        if candidate_id and candidate_id != drawing.active_recognition_id.id:
            candidate = drawing._current_candidates().filtered(lambda row: row.id == candidate_id)
            if not candidate:
                raise UserError('此识别项目已更新，请刷新后重试。')
            drawing._check_editable()
            drawing._select_candidate(candidate)
        return drawing.action_open_selection()

    def run_selection_recognition(self, drawing_id):
        self.ensure_one()
        self._nodo_check_selection_edit()
        return self._nodo_checked_drawing(drawing_id).action_recognize()

    def remove_selection_attachment(self, drawing_id):
        self.ensure_one()
        self._nodo_check_selection_edit()
        return self._nodo_checked_drawing(drawing_id).unlink()

    def _nodo_apply_cabinet(self, line, product, values, drawing=None, candidate=None):
        product.check_access('read')
        if (not product.active or not product.sale_ok or not product.nodo_cabinet_series
                or product.company_id and product.company_id != self.company_id):
            raise ValidationError('请选择当前公司可销售的柜体产品。')
        values = cabinet_values({**values, 'product_series': product.nodo_cabinet_series})
        if values['material'] not in dict(MATERIALS) or values['coating_type'] not in dict(COATINGS):
            raise ValidationError('请选择原报价规则支持的材质和喷塑工艺。')
        cabinet = next(iter(values['cabinet_configuration']['cabinets']), {})
        line_values = {
            'product_id': product.id, 'nodo_width': values['width_mm'], 'nodo_depth': values['depth_mm'],
            'nodo_height': values['height_mm'], 'nodo_base_height': values['base_height_mm'],
            'nodo_thickness': values['thickness_mm'], 'nodo_material': values['material'],
            'nodo_coating': values['coating_type'], 'nodo_color': values['display_color'] or '',
            'nodo_door': DOOR_KEYS.get(values['door_type']) if cabinet.get('door_manual') else False,
            'product_uom_qty': values['quantity'],
        }
        if drawing:
            line_values.update(nodo_source_drawing_id=drawing.id, nodo_drawing_candidate_id=candidate.id if candidate else False)
        catalog = self._nodo_accessory_catalog()
        previous = {entry.product_id.nodo_quote_accessory_name: entry for entry in line.nodo_attachments}
        accessories = accessory_values(
            values['accessory_selection_data'], catalog, 0, values['cabinet_configuration']['signature'],
        )
        if accessories['allocations'] or previous:
            commands = []
            for allocation in accessories['allocations']:
                name = allocation['name']
                existing = previous.pop(name, None)
                product_ids = catalog[name]['product_ids']
                if not existing and len(product_ids) > 1:
                    raise ValidationError(f'附件「{name}」有多个同名目录映射，请先核对当前公司的产品目录。')
                entry_values = {
                    'product_id': existing.product_id.id if existing else product_ids[0],
                    'selected': allocation['selected'], 'quantity': allocation['quantity'] or 1,
                    'quantity_pending': allocation['quantity'] is None,
                    'model_code': allocation['model_code'],
                    'actual_dimensions': json.dumps(allocation['manual_inputs'], ensure_ascii=False) if allocation['manual_inputs'] else False,
                }
                commands.append(Command.update(existing.id, entry_values) if existing else Command.create(entry_values))
            commands.extend(Command.delete(entry.id) for entry in previous.values())
            line_values['nodo_attachments'] = commands
        with workflow_change():
            if line:
                line.write(line_values)
            else:
                line = self.env['sale.order.line'].create({'order_id': self.id, **line_values})
        return line

    def _nodo_save_drawing_line(self, drawing, product, values):
        self.ensure_one()
        self._nodo_check_selection_edit()
        if drawing.order_id != self:
            raise AccessError('图纸不属于当前报价。')
        candidate = drawing.active_recognition_id
        return self._nodo_apply_cabinet(self._nodo_drawing_line(drawing, candidate), product, values, drawing, candidate)

    def save_selection_line(self, payload):
        self.ensure_one()
        self._nodo_check_selection_edit()
        if not isinstance(payload, dict):
            raise ValidationError('产品数据无效，请重新填写。')
        line = self.order_line.filtered(lambda row: row.id == payload.get('line_id'))
        if payload.get('line_id') and not line:
            raise AccessError('明细不属于当前报价。')
        display = payload.get('display_type')
        if display in ('line_section', 'line_note'):
            if line and line.display_type != display:
                raise ValidationError('请分别保存产品、分组和备注。')
            values = {'display_type': display, 'name': str(payload.get('text') or '')[:4000]}
            if line:
                line.write(values)
            else:
                line = self.env['sale.order.line'].create({'order_id': self.id, **values})
        else:
            if (not line and self.nodo_quote_drawing_ids) or (line and line.display_type):
                raise UserError('图纸产品请从「查看与选型」添加和修改。')
            if line.nodo_source_drawing_id and not line._nodo_is_independent_selection():
                raise UserError('这条明细来自图纸确认，请回图纸修改选型。')
            product = self.env['product.product'].browse(payload.get('product_id')).exists()
            if not product:
                raise ValidationError('请先选择柜体产品。')
            values = line._nodo_selection_values() if line else dict(SELECTION_DEFAULTS)
            values.update({key: payload[key] for key in SELECTION_DEFAULTS if key in payload})
            line = self._nodo_apply_cabinet(line, product, values)
        return {
            'line_id': line.id, 'product_name': line.product_id.name or '',
            'product_series': line.product_id.nodo_cabinet_series or '',
            'values': line._nodo_selection_values() if not line.display_type else {},
        }

    def copy_selection_line(self, line_id):
        self.ensure_one()
        self._nodo_check_selection_edit()
        line = self.order_line.filtered(lambda row: row.id == line_id and not row.display_type)
        if not line:
            raise UserError('请先保存产品后再复制。')
        copy = self._nodo_apply_cabinet(
            self.env['sale.order.line'], line.product_id, line._nodo_selection_values(), line.nodo_source_drawing_id,
        )
        copy.write({
            'nodo_customer_name': line.nodo_customer_name, 'nodo_manual_remark': line.nodo_manual_remark,
            'nodo_remark': line.nodo_remark,
        })
        return {'line_id': copy.id}

    def remove_selection_row(self, line_id=0, drawing_id=0, candidate_id=0):
        self.ensure_one()
        self._nodo_check_selection_edit()
        drawing = self._nodo_checked_drawing(drawing_id) if drawing_id else self.env['nodo.contract.drawing']
        if candidate_id:
            if not drawing:
                raise AccessError('识别项目不属于当前报价。')
            candidate = drawing._current_candidates().filtered(lambda row: row.id == candidate_id)
            if not candidate:
                raise AccessError('识别项目不属于当前图纸。')
            candidate.sudo().write({'excluded_from_quote': True})
            if candidate == drawing.active_recognition_id:
                drawing._select_candidate(drawing._current_candidates()[:1])
        if line_id:
            line = self.order_line.filtered(lambda row: row.id == line_id)
            if not line or (drawing and line.nodo_source_drawing_id != drawing):
                raise AccessError('明细行不属于当前报价或图纸。')
            line.unlink()
        if drawing and not drawing._current_candidates():
            drawing._trusted_write({'selection_row_hidden': True})
        return True

    def _get_product_catalog_domain(self):
        domain = super()._get_product_catalog_domain()
        if self.nodo_contract:
            domain &= Domain('product_tmpl_id.nodo_cabinet_series', '!=', False)
        return domain

    def _get_product_catalog_default_prices(self, products, **kwargs):
        if self.nodo_contract:
            return dict.fromkeys(products.ids, 0.0)
        return super()._get_product_catalog_default_prices(products, **kwargs)

    def _update_order_line_info(self, product, quantity, uom, child_field, **kwargs):
        if self.nodo_contract:
            self._nodo_check_selection_edit()
            if self.nodo_quote_drawing_ids:
                raise UserError('请从图纸的「查看与选型」添加柜体。')
            if child_field != 'order_line' or product not in product.filtered_domain(self._get_product_catalog_domain()):
                raise ValidationError('请选择当前公司的可销售柜体。')
            if uom and uom != product.uom_id:
                raise ValidationError('单柜报价使用柜体产品的基础计量单位。')
            if not checked_number(quantity) or quantity < 0 or quantity != int(quantity):
                raise ValidationError('单柜按台计，须为正整数。')
        return super()._update_order_line_info(product, quantity, uom, child_field, **kwargs)


class SaleSelectionLine(models.Model):
    _inherit = 'sale.order.line'

    nodo_source_drawing_id = fields.Many2one('nodo.contract.drawing', ondelete='set null', index=True, check_company=True, copy=False)
    nodo_drawing_candidate_id = fields.Many2one(
        'nodo.contract.drawing.candidate', ondelete='set null', index=True, check_company=True, copy=False,
    )

    def _nodo_selection_values(self):
        self.ensure_one()
        door = self.nodo_effective_door or ''
        values = cabinet_values({
            'product_series': self.product_id.nodo_cabinet_series, 'width_mm': self.nodo_width, 'depth_mm': self.nodo_depth,
            'height_mm': self.nodo_height, 'base_height_mm': self.nodo_base_height, 'quantity': self.product_uom_qty,
            'material': self.nodo_material, 'thickness_mm': self.nodo_thickness, 'coating_type': self.nodo_coating,
            'display_color': self.nodo_color, 'door_type': door, 'cabinet_configuration': {
                'cabinets': [{'door_type': door, 'door_manual': bool(self.nodo_door)}] if self.nodo_width else [],
            },
        })
        attachments = self.nodo_attachments
        if attachments:
            records = [{
                'name': row.product_id.nodo_quote_accessory_name, 'scope': 'cabinet', 'cabinet_index': 0,
                'selected': row.selected, 'quantity': None if row.quantity_pending else row.quantity,
                'manual_inputs': row._nodo_dimensions(), 'model_code': row.model_code or '',
            } for row in attachments]
            values['accessory_selection_data'] = {
                'version': 1, 'candidate_id': 0, 'manual_names': [item['name'] for item in records],
                'choices': {item['name']: item['selected'] for item in records}, 'allocations': records,
                'configured_signature': values['cabinet_configuration']['signature'],
            }
        return values

    def _nodo_is_independent_selection(self):
        self.ensure_one()
        if not self.nodo_source_drawing_id:
            return False
        if self.nodo_drawing_candidate_id:
            return self.nodo_drawing_candidate_id.recognition_token != self.nodo_source_drawing_id.recognition_token
        return self.nodo_source_drawing_id.order_line_id != self

    def _nodo_selection_row(self):
        self.ensure_one()
        return {
            **(self._nodo_selection_values() if not self.display_type else {}),
            'key': f'line_{self.id}', 'line_id': self.id, 'display_type': self.display_type, 'text': self.name,
            'source': 'drawing' if self.nodo_source_drawing_id else 'manual',
            'drawing_id': self.nodo_source_drawing_id.id or False,
            'candidate_id': self.nodo_drawing_candidate_id.id or False,
            'product_id': self.product_id.id or False, 'product_name': self.product_id.name or '',
            'independent': self._nodo_is_independent_selection(), 'state': 'confirmed',
        }
