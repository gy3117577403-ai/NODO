import base64
import json
import logging
from collections import Counter
from hashlib import sha256
from pathlib import PurePath
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.drawing_reader import (
    EXTENSIONS, FILE_LIMIT, inspect_file, original_config, original_read, pdf_dimension_view, text_suggestions,
)
from ..services.drawing_selection import (
    SELECTION_DEFAULTS, TEXT_LIMIT, accessory_overlap, accessory_values, cabinet_values, chinese_characters,
    drawing_part_numbers,
)
from ..services.quote_price import CABINET_SERIES, COATINGS, checked_number


_logger = logging.getLogger(__name__)
EDITABLE = set(SELECTION_DEFAULTS) | {'product_template_id', 'active_recognition_id', 'dimension_assist_data', 'selection_notes'}
IN_PROGRESS = ('queued', 'processing')


class QuoteDrawing(models.Model):
    _name = 'nodo.contract.drawing'
    _description = '销售报价图纸与选型'
    _order = 'id'
    _check_company_auto = True

    order_id = fields.Many2one('sale.order', required=True, ondelete='cascade', check_company=True, index=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    name = fields.Char(string='图纸文件', required=True)
    file_data = fields.Binary(string='图纸内容', required=True, attachment=True, copy=False)
    upload_files = fields.Json(string='待上传图纸', store=False, copy=False)
    file_kind = fields.Selection([('pdf', 'PDF'), ('image', '图片'), ('cad', 'CAD')], compute='_compute_kind')
    sha256 = fields.Char(readonly=True, copy=False)
    page_count = fields.Integer(string='图纸页数', readonly=True)
    page_label = fields.Char(string='页数', compute='_compute_kind')
    state = fields.Selection([('pending', '待选型'), ('confirmed', '已选型')], default='pending', required=True, readonly=True)
    product_series = fields.Selection(CABINET_SERIES, string='产品类型')
    product_template_id = fields.Many2one('product.template', string='产品主档', check_company=True)
    quantity = fields.Float(string='数量', default=1, digits='Product Unit')
    uom_id = fields.Many2one(related='product_template_id.uom_id', string='单位')
    width_mm = fields.Float(string='宽度（毫米）', digits=(12, 2))
    width_expression = fields.Char(string='单柜宽度输入', help='填写一个单柜宽度。')
    cabinet_configuration = fields.Json(string='门型配置', copy=False)
    depth_mm = fields.Float(string='深度（毫米）', digits=(12, 2))
    height_mm = fields.Float(string='高度（毫米）', digits=(12, 2))
    material = fields.Char(string='材质', default='SECC')
    thickness_mm = fields.Float(string='箱体料厚（毫米）', default=1.5, digits=(12, 3))
    base_height_mm = fields.Float(string='底座高度（毫米）', digits=(12, 2))
    coating_type = fields.Selection(COATINGS, string='喷塑', default='orange')
    display_color = fields.Char(string='颜色', default='RAL7035 浅灰')
    door_type = fields.Char(string='门型')
    selection_notes = fields.Text(string='附件选配与技术要求')
    accessory_selection_data = fields.Json(string='附件选配', copy=False)
    dimension_assist_data = fields.Json(string='辅助尺寸复核', copy=False)
    source_text = fields.Text(string='图纸文字', readonly=True, copy=False)
    order_line_id = fields.Many2one('sale.order.line', string='关联明细', ondelete='set null', check_company=True)
    reviewed_by = fields.Many2one('res.users', string='复核人员', readonly=True, copy=False)
    reviewed_at = fields.Datetime(string='复核时间', readonly=True, copy=False)
    selection_row_hidden = fields.Boolean(default=False, copy=False)
    can_edit_selection = fields.Boolean(compute='_compute_editable')
    recognition_state = fields.Selection([
        ('idle', '待识别'), ('queued', '排队中'), ('processing', '识别中'),
        ('review', '待复核'), ('done', '已复核'), ('failed', '识别未完成'),
    ], string='识别状态', default='idle', required=True, readonly=True, copy=False, index=True)
    recognition_token = fields.Char(readonly=True, copy=False)
    recognition_started_at = fields.Datetime(readonly=True, copy=False)
    recognition_finished_at = fields.Datetime(string='识别完成时间', readonly=True, copy=False)
    recognition_completed_pages = fields.Integer(string='已处理页数', readonly=True, copy=False)
    recognition_error = fields.Text(string='识别提示', readonly=True, copy=False)
    recognition_data = fields.Json(readonly=True, copy=False)
    orientation_data = fields.Json(string='图纸页面方向', readonly=True, copy=False)
    orientation_state = fields.Selection([
        ('queued', '旋正排队中'), ('processing', '旋正中'), ('ready', '图纸可查看'), ('failed', '旋正未完成'),
    ], default='ready', readonly=True, copy=False)
    orientation_token = fields.Char(readonly=True, copy=False)
    recognition_candidate_ids = fields.One2many(
        'nodo.contract.drawing.candidate', 'drawing_id', string='全部识别项目', readonly=True, copy=False,
    )
    active_recognition_id = fields.Many2one(
        'nodo.contract.drawing.candidate', string='识别项目', ondelete='set null', check_company=True, copy=False,
        domain="[('drawing_id', '=', id), ('recognition_token', '=', recognition_token), ('excluded_from_quote', '=', False)]",
    )
    recognition_summary = fields.Text(related='active_recognition_id.evidence_summary', string='识别依据')
    file_data_page = fields.Integer(related='active_recognition_id.page_number', string='原图页码')
    drawing_recognition_pending = fields.Boolean(compute='_compute_progress')
    drawing_recognition_version = fields.Char(compute='_compute_progress')

    @api.depends('name', 'page_count')
    def _compute_kind(self):
        for drawing in self:
            drawing.file_kind = EXTENSIONS.get(PurePath(drawing.name or '').suffix.lower())
            drawing.page_label = f'{drawing.page_count} 页' if drawing.page_count else '—'

    @api.depends('order_id.nodo_can_edit_selection', 'order_id.nodo_contract', 'order_id.locked')
    @api.depends_context('uid')
    def _compute_editable(self):
        for drawing in self:
            drawing.can_edit_selection = bool(
                drawing.order_id.nodo_contract and drawing.order_id.nodo_can_edit_selection and not drawing.order_id.locked
            )

    @api.depends('state', 'recognition_state', 'recognition_token', 'recognition_completed_pages', 'orientation_state')
    def _compute_progress(self):
        for drawing in self:
            drawing.drawing_recognition_pending = drawing.recognition_state in IN_PROGRESS
            drawing.drawing_recognition_version = ':'.join(map(str, (
                drawing.id, drawing.state, drawing.recognition_state, drawing.recognition_token,
                drawing.recognition_completed_pages, drawing.orientation_state,
            )))

    @api.readonly
    def get_drawing_recognition_progress(self):
        self.ensure_one()
        self.check_access('read')
        return {'version': self.drawing_recognition_version}

    def _check_editable(self):
        self.check_access('write')
        self.order_id._nodo_check_selection_edit()

    def _trusted_write(self, values):
        return super(QuoteDrawing, self.sudo()).write(values)

    def _values(self):
        self.ensure_one()
        return {name: self[name] for name in SELECTION_DEFAULTS}

    def _candidate_values(self):
        return {**self._values(), 'dimension_assist_data': self.dimension_assist_data,
                'selection_notes': self.selection_notes, 'product_template_id': self.product_template_id.id}

    def _prepare_values(self, vals, replacing=False):
        self.ensure_one()
        vals = dict(vals)
        product = self.env['product.template'].browse(vals['product_template_id']).exists() if 'product_template_id' in vals else (
            self.env['product.template'] if replacing else self.product_template_id
        )
        if product:
            product.check_access('read')
            if not product.sale_ok or not product.nodo_cabinet_series or (product.company_id and product.company_id != self.company_id):
                raise ValidationError('请选择当前公司可销售的柜体产品。')
            if 'product_template_id' in vals:
                vals['product_series'] = product.nodo_cabinet_series
            elif 'product_series' in vals and product.nodo_cabinet_series != vals['product_series']:
                vals['product_template_id'] = False
        if 'width_mm' in vals and 'width_expression' not in vals:
            vals['width_expression'] = f"{vals['width_mm']:g}" if vals['width_mm'] else ''
        base = SELECTION_DEFAULTS if replacing else self._values()
        normalized = cabinet_values({**base, **vals})
        catalog = self.order_id._nodo_accessory_catalog()
        if 'accessory_selection_data' in vals or normalized['accessory_selection_data']:
            normalized['accessory_selection_data'] = accessory_values(
                normalized['accessory_selection_data'], catalog, self.active_recognition_id.id or 0,
                normalized['cabinet_configuration']['signature'], require_quantity=True,
            )
        return {**vals, **normalized}

    @api.onchange('product_series', 'product_template_id', 'width_mm', 'width_expression', 'cabinet_configuration',
                  'depth_mm', 'height_mm', 'thickness_mm', 'material', 'coating_type', 'accessory_selection_data')
    def _onchange_selection(self):
        for drawing in self:
            values = drawing._values()
            if drawing.product_template_id != drawing._origin.product_template_id and drawing.product_template_id:
                values['product_template_id'] = drawing.product_template_id.id
            if drawing.width_mm != drawing._origin.width_mm and drawing.width_expression == drawing._origin.width_expression:
                values.pop('width_expression')
            drawing.update(drawing._prepare_values(values))

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for row in vals_list:
            if set(row) - {'order_id', 'name', 'file_data', 'upload_files'}:
                raise AccessError('上传入口只接收当前报价的图纸。')
            order = self.env['sale.order'].browse(row.get('order_id') or self.env.context.get('default_order_id')).exists()
            if not order:
                raise ValidationError('请先保存报价。')
            order._nodo_check_selection_edit()
            if not order.nodo_quote_drawing_ids and order.order_line.filtered(lambda line: not line.display_type):
                raise UserError('当前报价包含无图纸产品。请新建报价，再上传图纸关联选型。')
            uploads = row.get('upload_files') or [{'name': row.get('name'), **(row.get('file_data') or {})}]
            if not isinstance(uploads, list) or not 0 < len(uploads) <= 12:
                raise ValidationError('每次请选择 1 至 12 份图纸。')
            seen, total = set(), 0
            for upload in uploads:
                try:
                    name = PurePath(str(upload.get('name') or '').replace('\\', '/')).name
                    encoded = upload.get('content', '')
                    if not name or len(name) > 200 or not isinstance(encoded, str) or len(encoded) > FILE_LIMIT * 4 // 3 + 8:
                        raise ValueError('invalid drawing name or size')
                    content = base64.b64decode(encoded, validate=True)
                except (AttributeError, TypeError, ValueError) as error:
                    raise ValidationError('图纸文件名或内容无效，或超过单文件 24 MB。') from error
                digest = sha256(content).hexdigest()
                if (name, digest) in seen:
                    continue
                seen.add((name, digest))
                total += len(content)
                if total > 64 * 1024 * 1024:
                    raise ValidationError('一次上传的图纸合计须小于 64 MB。')
                _kind, count, pages = inspect_file(name, content)
                prepared.append({
                    'order_id': order.id, 'name': name, 'file_data': {'filename': name, 'content': encoded},
                    'sha256': digest, 'page_count': count, 'recognition_data': {'pages': pages},
                    'source_text': '\n'.join(page['raw_text'] for page in pages)[:TEXT_LIMIT],
                    'orientation_token': uuid4().hex,
                })
        records = super().create(prepared)
        for drawing in records:
            drawing._start_recognition()
        return records

    def write(self, vals):
        if not vals:
            return True
        self._check_editable()
        if set(vals) - EDITABLE:
            raise AccessError('图纸来源、识别结果和确认记录由流程保存。')
        for drawing in self:
            draft = dict(vals)
            if 'active_recognition_id' in draft:
                selected_id = draft.pop('active_recognition_id')
                candidate = drawing._current_candidates().filtered(lambda row: row.id == selected_id)
                if not candidate and selected_id:
                    raise ValidationError('请选择当前图纸本次识别返回的项目。')
                drawing._select_candidate(candidate)
            if draft:
                values = drawing._prepare_values(draft)
                drawing._validate_dimension_evidence(values.get('dimension_assist_data'))
                drawing._trusted_write({**values, 'state': 'pending'})
                drawing._save_review('pending')
        return True

    def unlink(self):
        self._check_editable()
        return super().unlink()

    def _validate_dimension_evidence(self, data):
        if not data:
            return
        if (not isinstance(data, dict) or data.get('version') != 1 or len(json.dumps(data)) > 100_000
                or data.get('candidate_id') != (self.active_recognition_id.id or 0)):
            raise ValidationError('框选记录与当前图纸项目不一致，请重新框选。')
        boxes = data.get('boxes') or {}
        if (not isinstance(boxes, dict) or set(boxes) - {'front', 'side'} or any(
            not isinstance(box, dict) or box.get('file_sha256') != self.sha256 for box in boxes.values()
        )):
            raise ValidationError('框选记录与当前图纸不一致，请重新框选。')

    def _current_candidates(self):
        self.ensure_one()
        return self.recognition_candidate_ids.filtered(
            lambda row: row.recognition_token == self.recognition_token and not row.excluded_from_quote
        )

    def _save_review(self, state):
        self.active_recognition_id.sudo().write({
            'review_values': self._candidate_values(), 'review_state': state,
            'reviewed_by': self.env.uid if state == 'confirmed' else False,
            'reviewed_at': fields.Datetime.now() if state == 'confirmed' else False,
        })

    def _select_candidate(self, candidate, apply_source=False):
        self.ensure_one()
        if candidate == self.active_recognition_id and not apply_source:
            return
        previous = self.active_recognition_id
        if previous and previous != candidate:
            self._save_review(self.state)
        if candidate:
            review = candidate.review_values if not apply_source else {}
            values = {**SELECTION_DEFAULTS, **(review or candidate.suggested_values or {})}
            values['product_template_id'] = (review or {}).get('product_template_id') or False
            values['dimension_assist_data'] = (review or {}).get('dimension_assist_data') or False
            values['selection_notes'] = (review or {}).get('selection_notes') or False
            self._trusted_write({'active_recognition_id': candidate.id})
            values = self._prepare_values(values, replacing=True)
            self._trusted_write({**values, 'state': candidate.review_state if review else 'pending'})
            if apply_source:
                self._save_review('pending')
        else:
            self._trusted_write({'active_recognition_id': False, 'dimension_assist_data': False, 'state': 'pending'})

    def _accessory_rows(self, candidate, manual):
        self.ensure_one()
        catalog = self.order_id._nodo_accessory_catalog()
        result = []
        raw = candidate.raw_result or {}
        text = raw.get('raw_text') or raw.get('text') or ''
        if not text and candidate:
            pages = (self.recognition_data or {}).get('pages', [])
            text = '\n'.join(str(page.get('raw_text') or page.get('text') or '')
                             for page in pages if page.get('source_page_number') == candidate.page_number)
        text = text or self.source_text or ''
        counts = Counter(chinese_characters(text))
        part_numbers = drawing_part_numbers(text)
        for name, item in catalog.items():
            evidence = accessory_overlap(name, counts)
            reference = next((code for code in item['part_numbers'] if code.upper() in part_numbers), None)
            if evidence or reference or name in manual:
                source = 'manual' if name in manual else 'part_number' if reference else 'drawing'
                result.append({
                    **item, 'source': source, 'overlap': (evidence or {}).get('text', ''),
                    'part_number': reference,
                    'match_rate': (evidence or {}).get('rate'),
                    'matched_count': (evidence or {}).get('matched_count', 0),
                    'name_count': (evidence or {}).get('name_count', 0),
                })
        return result

    @api.readonly
    def get_drawing_accessories(self, candidate_id=0, manual_names=None):
        self.ensure_one()
        self.check_access('read')
        candidate = self._current_candidates().filtered(lambda row: row.id == candidate_id)
        if candidate_id and not candidate:
            raise ValidationError('请选择当前图纸本次识别返回的项目。')
        data = self.accessory_selection_data or {}
        if data.get('candidate_id', 0) != candidate_id:
            data = {}
        manual = data.get('manual_names', []) if manual_names is None else manual_names
        if not isinstance(manual, list) or len(manual) > 100 or any(not isinstance(name, str) for name in manual):
            raise ValidationError('附件数据无效，请从附件库重新选择。')
        items = self._accessory_rows(candidate, manual)
        for item in items:
            item['selected'] = data.get('choices', {}).get(item['name'], item['source'] == 'manual')
        return {'items': items, 'candidate_id': candidate_id, 'pending': self.drawing_recognition_pending,
                'recognition_token': self.recognition_token or ''}

    @api.readonly
    def get_drawing_accessory_catalog(self):
        self.ensure_one()
        self.check_access('read')
        return list(self.order_id._nodo_accessory_catalog().values())

    def _config_path(self):
        self.ensure_one()
        return self.env['ir.config_parameter'].sudo().get_str(f'nodo_contract.recognition.config.{self.company_id.id}')

    def _start_recognition(self):
        self.ensure_one()
        config = self._config_path()
        if config:
            try:
                original_config(config)
            except UserError as error:
                self._trusted_write({'recognition_state': 'failed', 'recognition_error': error.args[0]})
                return
            self._trusted_write({'recognition_state': 'queued', 'recognition_token': uuid4().hex,
                                 'recognition_error': False, 'recognition_completed_pages': 0,
                                 'orientation_state': 'queued', 'active_recognition_id': False})
            self.env.ref('nodo_contract.ir_cron_quote_drawing').sudo()._trigger()
            return
        pages = (self.recognition_data or {}).get('pages', [])
        candidates = [proposal for page in pages if (proposal := text_suggestions(page))]
        if candidates:
            missing = [str(page['source_page_number']) for page in pages if not page['raw_text'].strip()]
            errors = [f"第 {'、'.join(missing)} 页没有可读取的文字层，请在原图核对。"] if missing else []
            self._store_recognition(pages, candidates, 'pdf-text', errors=errors)
        else:
            self._trusted_write({'recognition_state': 'failed', 'recognition_error':
                                 '未读到 PDF 文字层，原识图运行包未配置。可查看支持的原图并手工选型。'})

    def _store_recognition(self, pages, candidates, source, token=None, errors=(), orientation=None):
        token = token or uuid4().hex
        self._trusted_write({
            'recognition_token': token, 'recognition_state': 'review' if candidates else 'failed',
            'recognition_data': {'pages': pages, 'source': source}, 'active_recognition_id': False,
            'recognition_error': '\n'.join(map(str, errors))[:4000] if errors else (
                False if candidates else '未提取到可复核的图纸项目，可继续手工选型。'
            ),
            'recognition_completed_pages': len(pages), 'recognition_finished_at': fields.Datetime.now(),
            'orientation_state': 'ready', 'orientation_data': orientation or {},
        })
        created = self.env['nodo.contract.drawing.candidate'].sudo().create([{
            'drawing_id': self.id, 'name': str(item.get('name') or '待复核项目')[:180],
            'page_number': item['page'], 'recognition_token': token,
            'suggested_values': {key: value for key, value in (item.get('suggested') or {}).items()
                                 if key in SELECTION_DEFAULTS and key != 'accessory_selection_data'},
            'evidence_summary': str(item.get('summary') or '')[:4000], 'raw_result': item.get('raw') or {},
        } for item in candidates])
        if created:
            self._select_candidate(created[0])

    @api.model
    def _cron_process_recognition(self):
        drawing = self.sudo().search([('recognition_state', '=', 'queued')], limit=1)
        if not drawing:
            return
        self.env.cr.execute('SELECT id FROM nodo_contract_drawing WHERE id = %s FOR UPDATE SKIP LOCKED', (drawing.id,))
        if not self.env.cr.fetchone():
            return
        drawing.invalidate_recordset()
        if drawing.recognition_state != 'queued':
            return
        token = drawing.recognition_token
        drawing._trusted_write({'recognition_state': 'processing', 'recognition_started_at': fields.Datetime.now()})
        self.env.cr.commit()
        try:
            config = original_config(drawing._config_path())
            content, suffix = drawing.file_data.content, PurePath(drawing.name).suffix
            output = original_read('recognition', content, suffix, config)
            pages, candidates, errors = output.get('pages', []), output.get('candidates', []), output.get('errors', [])
            orientation = {'pages': {}}
            if drawing.file_kind in ('pdf', 'image'):
                for current in pages:
                    number = current.get('source_page_number', 0)
                    if number:
                        try:
                            orientation['pages'][str(number)] = original_read('orientation', content, suffix, config, page=number)
                        except UserError:
                            continue
        except (OSError, UserError, ValueError) as error:
            _logger.warning('NODO drawing recognition failed for %s: %s', drawing.id, type(error).__name__)
            pages, candidates, errors = [], [], [str(error) if isinstance(error, UserError) else '原识图执行失败。']
            orientation = None
        self.env.cr.commit()
        self.env.invalidate_all()
        if drawing.exists() and drawing.recognition_state == 'processing' and drawing.recognition_token == token:
            drawing._store_recognition(pages, candidates, 'original', token, errors, orientation)
        if self.sudo().search_count([('recognition_state', '=', 'queued')], limit=1):
            self.env.ref('nodo_contract.ir_cron_quote_drawing').sudo()._trigger()

    def action_recognize(self):
        self.ensure_one()
        self._check_editable()
        if self.recognition_state not in IN_PROGRESS:
            self._start_recognition()
        return True

    def action_cancel_recognition(self):
        self.ensure_one()
        self._check_editable()
        if self.recognition_state in IN_PROGRESS:
            self._trusted_write({'recognition_state': 'idle', 'recognition_token': uuid4().hex,
                                 'orientation_state': 'ready', 'recognition_error': '识别已取消。'})
        return True

    def action_apply_recognition(self):
        self.ensure_one()
        self._check_editable()
        if not self.active_recognition_id:
            raise UserError('请先选择本次识别项目。')
        self._select_candidate(self.active_recognition_id, apply_source=True)
        return True

    @api.readonly
    def get_drawing_orientation(self, page):
        self.ensure_one()
        self.check_access('read')
        if type(page) is not int or not 1 <= page <= max(self.page_count, 1):
            raise ValidationError('图纸页码无效。')
        return {'state': self.orientation_state, 'angle': (self.orientation_data or {}).get('pages', {}).get(
            str(page), {},
        ).get('angle', 0)}

    @api.readonly
    def get_dimension_view(self, page, point, rotation=0, orientation=0, rect=None):
        self.ensure_one()
        self.check_access('read')
        if (self.file_kind not in ('pdf', 'image') or type(page) is not int or not 1 <= page <= max(1, self.page_count)
                or any(angle not in (0, 90, 180, 270) for angle in (rotation, orientation))
                or not isinstance(point, list) or len(point) != 2
                or any(not checked_number(value) or not 0 <= value <= 1 for value in point)
                or not isinstance(rect, list) or len(rect) != 4 or any(not checked_number(value) for value in rect)
                or min(rect[:2]) < 0 or min(rect[2:]) < 0.005 or rect[0] + rect[2] > 1.000001 or rect[1] + rect[3] > 1.000001):
            raise ValidationError('图纸页码或选框无效，请重新框选。')
        content = self.file_data.content
        if self._config_path() and (self.recognition_data or {}).get('source') == 'original':
            output = original_read(
                'dimension', content, PurePath(self.name).suffix, original_config(self._config_path()),
                page=page, rect=rect, point=point, rotation=rotation, orientation=orientation,
            )
        elif self.file_kind == 'pdf' and self.source_text:
            output = pdf_dimension_view(content, page, rect, rotation, orientation)
        else:
            raise UserError('此页需要原识图运行包读取尺寸。请先对照原图，在右侧手工填写。')
        return {**output, 'file_sha256': self.sha256, 'candidate_id': self.active_recognition_id.id or 0}

    def action_open_selection(self):
        self.ensure_one()
        self.check_access('read')
        return {
            'type': 'ir.actions.act_window', 'name': '图纸与选型', 'res_model': self._name, 'res_id': self.id,
            'views': [(self.env.ref('nodo_contract.view_drawing_selection').id, 'form')], 'target': 'new',
            'context': {**self.env.context, 'dialog_size': 'extra-large'},
        }

    def action_confirm_selection(self):
        self.ensure_one()
        self._check_editable()
        if self.recognition_state in IN_PROGRESS:
            raise UserError('图纸仍在识别，请完成或取消识别后确认。')
        values = cabinet_values(self._values())
        if not values['product_series'] or not all(values[key] > 0 for key in (
            'width_mm', 'depth_mm', 'height_mm', 'thickness_mm',
        )):
            raise ValidationError('请填写柜型、宽度、深度、高度和料厚。')
        product = self.product_template_id
        if not product:
            product = self.env['product.template'].search([
                ('nodo_cabinet_series', '=', self.product_series), ('sale_ok', '=', True),
                ('company_id', 'in', [False, self.company_id.id]),
            ], limit=2)
        if len(product) != 1 or len(product.product_variant_ids) != 1:
            raise UserError('请为此柜型选择唯一的可销售产品。')
        values['accessory_selection_data'] = accessory_values(
            values['accessory_selection_data'], self.order_id._nodo_accessory_catalog(),
            self.active_recognition_id.id or 0, values['cabinet_configuration']['signature'], require_quantity=True,
        )
        line = self.order_id._nodo_save_drawing_line(self, product.product_variant_id, values)
        self._trusted_write({
            **values, 'order_line_id': line.id, 'state': 'confirmed', 'product_template_id': product.id,
            'selection_row_hidden': False, 'reviewed_by': self.env.uid, 'reviewed_at': fields.Datetime.now(),
        })
        self._save_review('confirmed')
        if self.recognition_state == 'review' and all(row.review_state == 'confirmed' for row in self._current_candidates()):
            self._trusted_write({'recognition_state': 'done'})
        return {'type': 'ir.actions.act_window_close'}


class QuoteDrawingCandidate(models.Model):
    _name = 'nodo.contract.drawing.candidate'
    _description = '报价图纸识别项目与复核记录'
    _order = 'page_number, id'
    _check_company_auto = True

    drawing_id = fields.Many2one('nodo.contract.drawing', required=True, ondelete='cascade', check_company=True, index=True)
    company_id = fields.Many2one(related='drawing_id.company_id', store=True, index=True)
    name = fields.Char(required=True)
    page_number = fields.Integer(string='页码', required=True)
    recognition_token = fields.Char(required=True, index=True)
    suggested_values = fields.Json(readonly=True)
    evidence_summary = fields.Text(readonly=True)
    raw_result = fields.Json(readonly=True)
    review_values = fields.Json(readonly=True)
    review_state = fields.Selection([('pending', '待复核'), ('confirmed', '已复核')], default='pending', readonly=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_at = fields.Datetime(readonly=True)
    excluded_from_quote = fields.Boolean(default=False)
