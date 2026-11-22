import base64
import json
from collections import Counter
from io import BytesIO
from unittest.mock import Mock, patch

from PIL import Image
from reportlab.pdfgen import canvas

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..services.drawing_selection import accessory_overlap, chinese_characters


@tagged('nodo', 'post_install', '-at_install')
class TestDrawingSelection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.seller = new_test_user(cls.env, login='drawing-sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.other = new_test_user(cls.env, login='other-drawing-sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.cabinet = cls.env['product.product'].create({
            'name': 'JA 柜体', 'nodo_cabinet_series': 'JA', 'taxes_id': [Command.clear()],
        })
        cls.board = cls.env['product.product'].create({
            'name': '柜体安装板', 'nodo_quote_accessory_name': '安装板', 'default_code': 'BOARD-N7',
        })
        cls.customer = cls.env['res.partner'].create({'name': '砚汀设备'})
        cls.price = cls.env['product.pricelist'].create({
            'name': '人民币', 'currency_id': cls.env.ref('base.CNY').id,
        })

    def _new_order(self):
        return self.env['sale.order'].with_user(self.seller).with_context(nodo_quote_entry=True).create({
            'partner_id': self.customer.id, 'pricelist_id': self.price.id,
            'nodo_quote_drawing_ids': [],
        })

    def _upload(self, order, filename, content):
        return self.env['nodo.contract.drawing'].with_user(self.seller).create({
            'order_id': order.id, 'name': filename,
            'file_data': {'filename': filename, 'content': base64.b64encode(content).decode()},
        })

    def test_native_quote_pdf_frames_and_confirm_same_line(self):
        defaults = self.env['sale.order'].with_user(self.seller).with_context(nodo_quote_entry=True).default_get(
            ['nodo_contract', 'quotation_document_ids'],
        )
        self.assertTrue(defaults['nodo_contract'])
        self.assertEqual(defaults['quotation_document_ids'], [])
        order = self._new_order()
        self.assertTrue(order.nodo_contract)
        self.assertIn(self.env.ref('nodo_base.group_role_sales'), self.env.ref('sale.menu_sale_quotations').group_ids)
        stream = BytesIO()
        drawing_pdf = canvas.Canvas(stream, pagesize=(600, 800))
        drawing_pdf.drawString(75, 710, 'JA')
        drawing_pdf.drawString(75, 620, 'width 900')
        drawing_pdf.drawString(75, 400, 'height 1800')
        drawing_pdf.drawString(420, 620, 'depth 400')
        drawing_pdf.save()
        drawing = self._upload(order, 'JA.pdf', stream.getvalue())
        self.assertEqual(drawing.recognition_state, 'review')
        self.assertEqual((drawing.width_mm, drawing.depth_mm, drawing.height_mm), (900, 400, 1800))
        front = drawing.get_dimension_view(1, [0.25, 0.4], rect=[0.05, 0.15, 0.4, 0.55])
        selected = {token['id']: token['value'] for token in front['tokens']}
        self.assertEqual(selected[front['horizontal']], 900)
        self.assertEqual(selected[front['vertical']], 1800)
        with self.assertRaises(ValidationError):
            order.action_nodo_submit_costing()
        with self.assertRaises(AccessError):
            drawing.with_user(self.other).get_drawing_accessory_catalog()
        drawing.write({'product_template_id': self.cabinet.product_tmpl_id.id, 'quantity': 2})
        drawing.action_confirm_selection()
        line = drawing.order_line_id
        self.assertEqual(order.order_line, line)
        self.assertEqual((line.product_uom_qty, line.price_unit), (2, 0))
        drawing.write({'width_mm': 780})
        drawing.action_confirm_selection()
        self.assertEqual(order.order_line, line)
        self.assertEqual(line.nodo_effective_door, '前单开门后背板')
        self.assertEqual(order.get_selection_table()['rows'][0]['state'], 'confirmed')

    def test_missing_original_ocr_keeps_image_available_for_manual_selection(self):
        order = self._new_order()
        stream = BytesIO()
        Image.new('RGB', (200, 200), 'white').save(stream, format='PNG')
        drawing = self._upload(order, '原图.png', stream.getvalue())
        self.assertEqual(drawing.recognition_state, 'failed')
        self.assertIn('运行包未配置', drawing.recognition_error)
        drawing.write({'product_template_id': self.cabinet.product_tmpl_id.id,
                       'width_mm': 900, 'depth_mm': 400, 'height_mm': 1800})
        drawing.action_confirm_selection()
        self.assertEqual(drawing.order_line_id.product_id, self.cabinet)

    def test_text_dimensions_and_accessory_matches_wait_for_review(self):
        stream = BytesIO()
        pdf = canvas.Canvas(stream, pagesize=(600, 800))
        for y, label in enumerate((
            'JA', 'width 900', 'width 800', 'depth 400', 'overall height 1900', 'cabinet height 1800',
            'base height 100', 'BOARD-N7',
        ), start=1):
            pdf.drawString(135, 710 - 45 * y, label)
        pdf.save()
        order = self._new_order()
        drawing = self._upload(order, '柜体尺寸.pdf', stream.getvalue())
        self.assertEqual((drawing.width_mm, drawing.depth_mm, drawing.height_mm), (0, 400, 0))
        result = drawing.get_dimension_view(1, [0.5, 0.5], rect=[0.1, 0.1, 0.8, 0.85])
        self.assertIsNone(result['vertical'])
        self.assertEqual({token['dimension_key'] for token in result['tokens'] if token['axis'] == 'vertical'},
                         {'total_height', 'cabinet_height', 'base_height'})
        candidate_id = drawing.active_recognition_id.id
        board, = drawing.get_drawing_accessories(candidate_id)['items']
        self.assertEqual((board['name'], board['source'], board['selected']), ('安装板', 'part_number', False))
        drawing.write({'product_template_id': self.cabinet.product_tmpl_id.id, 'width_mm': 900, 'height_mm': 1800})
        drawing.action_confirm_selection()
        self.assertFalse(drawing.order_line_id.nodo_attachments)
        drawing.write({'accessory_selection_data': {'candidate_id': candidate_id, 'choices': {'安装板': True}}})
        drawing.action_confirm_selection()
        accessory = drawing.order_line_id.nodo_attachments
        self.assertEqual(accessory.product_id, self.board)
        self.assertTrue(accessory.quantity_pending)

    def test_vision_local_region_requires_review_before_updating_quote(self):
        pdf, crop = BytesIO(), BytesIO()
        image = Image.new('RGB', (240, 200), 'white')
        image.save(pdf, format='PDF')
        image.save(crop, format='PNG')
        drawing = self._upload(self._new_order(), '局部补读.pdf', pdf.getvalue())
        drawing.write({'product_template_id': self.cabinet.product_tmpl_id.id,
                       'width_mm': 900, 'depth_mm': 400, 'height_mm': 1800})
        source = drawing.get_drawing_vision()['source']
        region = [0.2, 0.1, 0.4, 0.2]
        encoded = base64.b64encode(crop.getvalue()).decode()
        values = [
            ('width_mm', '890', 'mm', '宽 890 mm'),
            ('overall_height_mm', '1900', 'mm', '含底座总高 1900 mm'),
            ('thickness_mm', '105.4', 'mm', '板厚 10.54 mm'),
            ('requirement', None, None, '配焊铰链'),
            ('accessory', None, None, '配安装板'),
        ]
        payload = {'items': [
            {'field': field, 'value': value, 'unit': unit, 'text': text, 'status': 'explicit',
             'box': [100, 200, 400, 800]} for field, value, unit, text in values
        ]}
        response = Mock(status_code=200, headers={})
        response.json.return_value = {'status': 'completed', 'model': 'gpt-6.1-sol', 'output': [{
            'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(payload)}],
        }]}
        with (patch.object(type(drawing), '_vision_config', return_value=('fixture-key', 'gpt-6.1-sol')),
              patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=120),
              patch('odoo.addons.nodo_contract.services.drawing_vision.requests.post', return_value=response) as post):
            with self.assertRaises(AccessError):
                drawing.with_user(self.other).queue_drawing_vision(source, 1, 0, region, encoded)
            with self.assertRaises(ValidationError):
                drawing.queue_drawing_vision({**source, 'sha256': 'stale'}, 1, 0, region, encoded)
            self.assertEqual(drawing.queue_drawing_vision(source, 1, 90, region, encoded)['state'], 'queued')
            with self.assertRaises(UserError):
                drawing.queue_drawing_vision(source, 1, 90, region, encoded)
            drawing._cron_process_drawing_vision()
        post.assert_called_once()
        args = post.call_args.kwargs['json']
        image_sent, = args['input'][0]['content']
        self.assertEqual(image_sent, {'type': 'input_image', 'detail': 'high', 'image_url': 'data:image/png;base64,' + encoded})
        self.assertFalse(args['store'])
        run, = drawing.get_drawing_vision()['runs']
        self.assertNotIn('crop', drawing.sudo().vision_job)
        self.assertEqual(run['rotation'], 90)
        self.assertAlmostEqual(run['items'][0]['rect'][0], 0.24)
        self.assertEqual((drawing.width_mm, drawing.height_mm, drawing.thickness_mm), (900, 1800, 1.5))
        with self.assertRaises(UserError):
            drawing.review_drawing_vision(run['id'], '1', 'apply', 800)
        with self.assertRaises(ValidationError):
            drawing.review_drawing_vision(run['id'], '3', 'apply', 1.5)
        drawing.review_drawing_vision(run['id'], '1', 'keep')
        drawing.review_drawing_vision(run['id'], '2', 'apply', 1800)
        drawing.review_drawing_vision(run['id'], '4', 'note')
        self.assertIn('配焊铰链', drawing.selection_notes)
        drawing.action_confirm_selection()
        line = drawing.order_line_id
        self.assertEqual((line.nodo_width, line.nodo_height, line.price_unit), (900, 1900, 0))
        self.assertFalse(line.nodo_attachments)

    def test_vision_missing_and_incomplete_do_not_offer_a_result(self):
        pdf, crop = BytesIO(), BytesIO()
        image = Image.new('RGB', (100, 100), 'white')
        image.save(pdf, format='PDF')
        image.save(crop, format='PNG')
        drawing = self._upload(self._new_order(), '扫描图.pdf', pdf.getvalue())
        review = drawing.get_drawing_vision()
        self.assertFalse(review['configured'])
        region = [0.15, 0.1, 0.4, 0.35]
        encoded = base64.b64encode(crop.getvalue()).decode()
        with self.assertRaises(UserError):
            drawing.queue_drawing_vision(review['source'], 1, 0, region, encoded)
        response = Mock(status_code=200)
        response.json.return_value = {'status': 'incomplete'}
        with (patch.object(type(drawing), '_vision_config', return_value=('fixture-key', 'gpt-6.1-sol')),
              patch.object(type(self.env['ir.cron']), '_commit_progress', return_value=120),
              patch('odoo.addons.nodo_contract.services.drawing_vision.requests.post', return_value=response)):
            drawing.queue_drawing_vision(review['source'], 1, 0, region, encoded)
            drawing._cron_process_drawing_vision()
        review = drawing.get_drawing_vision()
        self.assertEqual(review['state'], 'failed')
        self.assertIn('未完整返回', review['error'])
        self.assertFalse(review['runs'])

    def test_accessory_match_counts_repeated_hanzi_without_model_digits(self):
        counts = Counter(chinese_characters('安装，序号 100'))
        self.assertEqual(accessory_overlap('安装板 99', counts), {
            'text': '安装', 'matched_count': 2, 'name_count': 3, 'rate': 66.7,
        })
        self.assertIsNone(accessory_overlap('安装安装板', counts))
