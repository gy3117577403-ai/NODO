from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.misc import format_amount


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussPurchase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        cls.buyer = new_test_user(
            env, login='share_buyer@nodo.test',
            groups='purchase.group_purchase_user,nodo_base.group_role_purchase',
        )
        cls.planner = new_test_user(
            env, login='share_purchase_planner@nodo.test',
            groups='purchase.group_purchase_user,nodo_base.group_role_production',
        )
        cls.shopfloor = new_test_user(
            env, login='share_purchase_shopfloor@nodo.test',
            groups='nodo_base.group_role_operator',
        )
        cls.outsider = new_test_user(
            env, login='share_purchase_outsider@nodo.test', groups='purchase.group_purchase_user',
        )
        cls.supplier = cls.env['res.partner'].create({'name': '协作供应方'})
        product = cls.env['product.product'].create({
            'name': '工装维护服务', 'type': 'service', 'purchase_ok': True,
        })
        cls.order = cls.env['purchase.order'].create({
            'partner_id': cls.supplier.id,
            'order_line': [Command.create({
                'product_id': product.id,
                'product_qty': 2,
                'price_unit': 480,
                'tax_ids': [Command.clear()],
            })],
        })
        cls.production = cls.env.ref('nodo_base.channel_production_coordination')
        cls.service = cls.env['nodo.discuss.record'].with_user(cls.buyer)
        cls.reference = {'model': 'purchase.order', 'id': cls.order.id}

    def test_purchase_form_and_picker_use_purchase_card(self):
        order = self.order.with_user(self.buyer)
        view = order.get_view(view_id=self.env.ref('purchase.purchase_order_form').id)
        self.assertIn('name="action_nodo_share_to_chat"', view['arch'])
        action = order.action_nodo_share_to_chat()
        self.assertEqual(action['tag'], 'nodo_share_record')
        self.assertEqual(action['params'], self.reference)
        self.assertIn(
            {'model': 'purchase.order', 'label': '采购询价单和采购单'},
            self.service.get_record_card_types(),
        )
        self.assertEqual(self.order.amount_total, 960)
        states = dict(order._fields['state']._description_selection(order.env))
        amount = format_amount(order.env, 960, order.currency_id)
        for state, label, status_type in (
            ('draft', '采购询价单', 'warning'),
            ('sent', '采购询价单', 'info'),
            ('to approve', '采购单', 'warning'),
            ('purchase', '采购单', 'success'),
            ('cancel', '采购单', 'muted'),
        ):
            with self.subTest(state=state):
                self.order.state = state
                [card] = self.service.get_record_cards([self.reference])
                self.assertEqual(card, {
                    **self.reference,
                    'title': f'{label} {self.order.name}',
                    'subtitle': f'{self.supplier.name} · {amount}',
                    'status': states[state],
                    'status_type': status_type,
                })

    def test_share_to_production_and_filter_cards_by_viewer_access(self):
        self.assertEqual(self.production.name, '生产协调')
        for user in self.buyer | self.planner | self.shopfloor:
            self.assertIn(user.partner_id, self.production.channel_partner_ids)
        self.assertIn(
            self.production.id, [item['id'] for item in self.service.search_share_targets('channel', '生产')],
        )

        result = self.service.share_record(
            'purchase.order', self.order.id, 'channel', self.production.id,
            note='请核对工装维护排期。',
        )
        message = self.env['mail.message'].browse(result['message_id'])
        self.assertEqual(result['channel_id'], self.production.id)
        self.assertEqual(message.res_id, self.production.id)
        self.assertEqual(message.author_id, self.buyer.partner_id)
        self.assertEqual(message.message_type, 'comment')
        self.assertEqual(message.subtype_id, self.env.ref('mail.mt_comment'))
        self.assertIn(f'/odoo/purchase.order/{self.order.id}', message.body)
        self.assertIn('请核对工装维护排期。', message.body)
        self.assertNotIn(self.supplier.name, message.body)

        self.assertTrue(message.with_user(self.shopfloor).has_access('read'))
        self.assertTrue(self.service.with_user(self.planner).get_record_cards([self.reference]))
        self.assertEqual(self.service.with_user(self.shopfloor).get_record_cards([self.reference]), [])
        self.assertNotIn(
            'purchase.order',
            [item['model'] for item in self.service.with_user(self.shopfloor).get_record_card_types()],
        )

    def test_share_requires_order_access_and_channel_membership(self):
        with self.assertRaisesRegex(AccessError, '单据不可访问'):
            self.service.with_user(self.shopfloor).share_record(
                'purchase.order', self.order.id, 'channel', self.production.id,
            )
        self.assertTrue(self.order.with_user(self.outsider).has_access('read'))
        with self.assertRaisesRegex(AccessError, '无法在此会话发言'):
            self.service.with_user(self.outsider).share_record(
                'purchase.order', self.order.id, 'channel', self.production.id,
            )

    def test_purchase_share_obeys_announcement_posting_groups(self):
        announcement = self.env.ref('mail.channel_all_employees')
        self.assertTrue(announcement.with_user(self.buyer).is_member)
        targets = self.service.search_share_targets('channel')
        self.assertNotIn(announcement.id, [item['id'] for item in targets])
        with self.assertRaises(AccessError):
            self.service.share_record('purchase.order', self.order.id, 'channel', announcement.id)
