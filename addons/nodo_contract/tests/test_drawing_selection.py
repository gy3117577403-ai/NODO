import base64
from collections import Counter
from io import BytesIO

from PIL import Image
from reportlab.pdfgen import canvas

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
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
        cls.board = cls.env['product.product'].create({'name': '柜体安装板', 'nodo_quote_accessory_name': '安装板'})
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

    def test_accessory_match_counts_repeated_hanzi_without_model_digits(self):
        counts = Counter(chinese_characters('安装，序号 100'))
        self.assertEqual(accessory_overlap('安装板 99', counts), {
            'text': '安装', 'matched_count': 2, 'name_count': 3, 'rate': 66.7,
        })
        self.assertIsNone(accessory_overlap('安装安装板', counts))
