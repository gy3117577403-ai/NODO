from unittest.mock import patch

from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('nodo', 'post_install', '-at_install')
class TestContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency = cls.env.ref('base.CNY')
        cls.company = cls.env['res.company'].create({'name': '岚格柜体', 'currency_id': cls.currency.id})
        cls.env = cls.env(context={**cls.env.context, 'allowed_company_ids': [cls.company.id]})
        for role in ('sales', 'costing', 'approval'):
            setattr(cls, role, new_test_user(
                cls.env, login=f'{role}-contract@nodo.test', groups=f'nodo_base.group_role_{role}',
                company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
            ))
        cls.another_seller = new_test_user(
            cls.env, login='another-contract@nodo.test', groups='nodo_base.group_role_sales',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)],
        )
        cls.customer = cls.env['res.partner'].create({'name': '砚湾设备'})
        cls.pricelist = cls.env['product.pricelist'].create({
            'name': '人民币报价', 'currency_id': cls.currency.id, 'company_id': cls.company.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'JA 单柜', 'nodo_cabinet_series': 'JA', 'list_price': 999, 'taxes_id': [Command.clear()],
        })
        cls.accessory = cls.env['product.product'].create({
            'name': '安装板', 'nodo_quote_accessory_name': '安装板', 'nodo_quote_accessory_category': '通用附件',
        })
        cls.orders = cls.env['sale.order']

    def _quote(self):
        return self.orders.with_user(self.sales).with_context(default_nodo_contract=True).create({
            'partner_id': self.customer.id, 'pricelist_id': self.pricelist.id,
            'nodo_selection_ids': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': 2,
                'nodo_width': 900, 'nodo_depth': 400, 'nodo_height': 1800,
                'nodo_manual_remark': True, 'nodo_remark': '每台配安装板。',
                'tax_ids': [Command.clear()],
                'nodo_attachments': [Command.create({
                    'product_id': self.accessory.id, 'quantity': 1, 'actual_dimensions': '{"长度": 600}',
                })],
            })],
        })

    def _calculate_with_service_result(self, costing_quote):
        line = costing_quote.order_line
        result = {
            line.id: {
                'price_unit': 1234.50,
                'response': {'quote_line_id': 'contract-test-price'},
                'item': {'quote_cost_display': {'values': {'材料成本': '650.00'}}},
            },
        }
        # Supply a fixed response for workflow assertions. The genuine pricing
        # rules and their numerical results require the separate original service.
        with patch.object(type(costing_quote), '_nodo_calculate', return_value=result):
            costing_quote.action_nodo_calculate()

    def test_selection_survives_missing_pricing_and_cannot_be_issued(self):
        quote = self._quote()
        self.assertEqual(quote.order_line.price_unit, 0)
        self.assertEqual(quote.order_line.nodo_effective_door, '前双开门后背板')
        self.assertEqual(quote.order_line.nodo_attachments._nodo_dimensions(), {'长度': 600})
        self.assertFalse(quote.with_user(self.another_seller).has_access('read'))
        with self.assertRaises(AccessError):
            quote.order_line.write({'price_unit': 1})
        with self.assertRaises(AccessError):
            quote.write({'nodo_quote_stage': 'approved'})
        quote.action_nodo_submit_costing()
        costing_quote = quote.with_user(self.costing)
        with self.assertRaisesRegex(UserError, '未配置原报价服务'):
            costing_quote.action_nodo_calculate()
        self.assertEqual(quote.nodo_quote_stage, 'costing')
        self.assertFalse(quote.nodo_quote_ready)
        with self.assertRaises(UserError):
            quote.action_nodo_submit_approval()
        with self.assertRaises(UserError):
            quote.action_nodo_quote_pdf()
        with self.assertRaises(UserError):
            quote.action_nodo_quote_excel()
        with self.assertRaises(UserError):
            quote.with_user(self.approval).action_confirm()

    def test_sales_quotation_form_excludes_unreadable_native_cost_columns(self):
        view_id = self.env.ref('sale.view_order_form').id
        arch = etree.fromstring(self.orders.with_user(self.sales).get_view(view_id, 'form')['arch'])
        self.assertTrue(arch.xpath(".//field[@name='nodo_quote_drawing_ids']"))
        self.assertTrue(arch.xpath(".//field[@name='tax_totals']"))
        names = {node.get('name') for node in arch.xpath(".//field[@name='order_line']//field")}
        self.assertFalse(names & {'margin', 'margin_percent', 'purchase_price'})

    def test_selected_version_is_approved_issued_accepted_and_confirmed(self):
        quote = self._quote()
        quote.action_nodo_submit_costing()
        self._calculate_with_service_result(quote.with_user(self.costing))
        quote.action_nodo_submit_approval()
        with self.assertRaises(AccessError):
            quote.action_nodo_approve()

        approver_quote = quote.with_user(self.approval)
        approver_quote.action_nodo_approve()
        version = approver_quote.nodo_active_version_id
        self.assertEqual(version.approved_by, self.approval)
        self.assertFalse(version.with_user(self.sales).has_access('read'))
        document = quote._nodo_customer_document()
        self.assertEqual(document['lines'][0]['unit_price'], 1234.50)
        self.assertEqual(document['lines'][0]['remark'], '每台配安装板。')
        self.assertEqual(document['total'], 2469)
        self.assertNotIn('材料成本', str(document))
        self.assertEqual(quote.action_nodo_quote_pdf()['report_name'], 'nodo_contract.customer_quote_pdf')
        self.assertTrue(quote.action_nodo_quote_excel()['url'].endswith(f'/{quote.id}/xlsx'))

        quote.action_nodo_mark_sent()
        with self.assertRaises(ValidationError):
            quote.action_nodo_accept()
        quote.write({'nodo_acceptance_note': '客户邮件确认 V1。'})
        quote.action_nodo_accept()
        with self.assertRaises(AccessError):
            quote.action_confirm()

        approver_quote.action_confirm()
        self.assertEqual((quote.state, quote.nodo_quote_stage), ('sale', 'sale'))
        self.assertEqual(quote.amount_total, document['total'])
        self.assertEqual(quote._nodo_customer_document(), document)

    def test_returned_version_is_kept_and_cost_override_clears_active_amount(self):
        quote = self._quote()
        quote.action_nodo_submit_costing()
        costing_quote = quote.with_user(self.costing)
        self._calculate_with_service_result(costing_quote)
        costing_quote.order_line.write({'nodo_coefficient': 0.95})
        self.assertFalse(quote.nodo_quote_ready)
        self.assertEqual(quote.order_line.price_unit, 0)
        self._calculate_with_service_result(costing_quote)
        quote.action_nodo_submit_approval()
        quote.with_user(self.approval).action_nodo_return_selection()
        self.assertEqual(quote.nodo_quote_stage, 'selection')
        self.assertEqual(set(costing_quote.nodo_quote_versions.mapped('number')), {1, 2})
        self.assertFalse(quote.nodo_quote_ready)
