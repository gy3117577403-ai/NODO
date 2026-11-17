from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.misc import format_amount


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussSale(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')
        cls.seller = new_test_user(
            cls.env, login='share_seller@nodo.test',
            groups='sales_team.group_sale_salesman,nodo_base.group_role_sales',
        )
        cls.approver = new_test_user(
            cls.env, login='share_approval@nodo.test',
            groups='sales_team.group_sale_salesman_all_leads,nodo_base.group_role_approval',
        )
        cls.operator = new_test_user(
            cls.env, login='share_operator@nodo.test', groups='nodo_base.group_role_operator',
        )
        cls.customer = cls.env['res.partner'].create({'name': '协作客户'})
        cls.product = cls.env['product.product'].create({
            'name': '控制柜', 'taxes_id': [Command.clear()],
        })
        cls.orders = cls.env['sale.order']
        cls.quote = cls.orders.create({
            'partner_id': cls.customer.id, 'user_id': cls.seller.id,
            'order_line': [Command.create({
                'product_id': cls.product.id, 'product_uom_qty': 2, 'price_unit': 500,
            })],
        })
        cls.other_quote = cls.orders.create({'partner_id': cls.customer.id, 'user_id': cls.approver.id})
        cls.channels = cls.env['discuss.channel']
        cls.service = cls.env['nodo.discuss.record'].with_user(cls.seller)
        cls.reference = {'model': cls.quote._name, 'id': cls.quote.id}

    def test_card_uses_sale_values_and_current_native_status(self):
        self.assertEqual(self.quote.amount_total, 1000)
        states = dict(self.orders._fields['state']._description_selection(self.service.env))
        [card] = self.service.get_record_cards([self.reference])
        self.assertEqual(card, {
            **self.reference,
            'title': f'报价单 {self.quote.name}',
            'subtitle': f'{self.customer.name} · {format_amount(self.service.env, 1000, self.quote.currency_id)}',
            'status': states['draft'], 'status_type': 'warning',
        })
        self.quote.write({'state': 'sent'})
        [updated] = self.service.get_record_cards([self.reference])
        self.assertEqual((updated['status'], updated['status_type']), (states['sent'], 'info'))

    def test_sale_card_types_and_batch_respect_model_and_record_access(self):
        self.assertEqual(self.service.get_record_card_types(), [
            {'model': 'sale.order', 'label': '报价单和销售订单'},
        ])
        self.assertEqual(self.service.with_user(self.operator).get_record_card_types(), [])
        self.assertFalse(self.other_quote.with_user(self.seller).has_access('read'))
        references = [self.reference, {**self.reference, 'id': self.other_quote.id}]
        self.assertEqual([card['id'] for card in self.service.get_record_cards(references)], [self.quote.id])
        self.assertEqual(self.service.with_user(self.operator).get_record_cards(references), [])

    def test_share_to_person_posts_canonical_link_and_escapes_note(self):
        self.assertEqual(self.quote.with_user(self.seller).action_nodo_share_to_chat()['params'], self.reference)
        self.assertIn(
            {'id': self.operator.partner_id.id, 'name': self.operator.partner_id.name},
            self.service.search_share_targets('person'),
        )
        result = self.service.share_record('sale.order', self.quote.id, 'person', self.operator.partner_id.id,
                                           '请核对 <柜体>\n和图纸')
        channel = self.channels.browse(result['channel_id'])
        message = channel.message_ids.filtered(lambda item: item.id == result['message_id'])
        self.assertEqual(channel.channel_type, 'chat')
        self.assertEqual(channel.channel_partner_ids, self.seller.partner_id | self.operator.partner_id)
        self.assertEqual(message.author_id, self.seller.partner_id)
        self.assertEqual(message.subtype_id, self.env.ref('mail.mt_comment'))
        self.assertIn(f'/odoo/sale.order/{self.quote.id}', message.body)
        self.assertIn('请核对 &lt;柜体&gt;', message.body)
        self.assertIn('和图纸', message.body)
        self.assertNotIn(self.customer.name, message.body)
        self.assertEqual(self.service.with_user(self.operator).get_record_cards([self.reference]), [])

    def test_share_rechecks_record_read_access_and_conversation_membership(self):
        private_group = self.channels._create_group(self.admin | self.operator, name='私有协调群')
        self.assertEqual(self.service.search_share_targets('group', '私有协调群'), [])
        with self.assertRaisesRegex(AccessError, '此会话发言'):
            self.service.share_record('sale.order', self.quote.id, 'group', private_group.id)
        with self.assertRaisesRegex(AccessError, '单据不可访问'):
            self.service.share_record('sale.order', self.other_quote.id, 'person', self.operator.partner_id.id)
        with self.assertRaisesRegex(AccessError, '单据不可访问'):
            self.quote.with_user(self.operator).action_nodo_share_to_chat()

        group = self.channels._create_group(self.seller | self.operator, name='协作群')
        self.assertEqual(self.service.search_share_targets('group', '协作群'), [{'id': group.id, 'name': '协作群'}])
        sent = self.service.share_record('sale.order', self.quote.id, 'group', group.id)
        self.assertIn(sent['message_id'], group.message_ids.ids)

    def test_announcement_blocks_seller_and_allows_approval_role(self):
        announcement = self.env.ref('mail.channel_all_employees')
        self.assertNotIn(announcement.id, [target['id'] for target in self.service.search_share_targets('channel')])
        with self.assertRaisesRegex(AccessError, '可发言权限组'):
            self.service.share_record('sale.order', self.quote.id, 'channel', announcement.id)
        service = self.service.with_user(self.approver)
        self.assertIn(announcement.id, [target['id'] for target in service.search_share_targets('channel')])
        result = service.share_record('sale.order', self.quote.id, 'channel', announcement.id)
        self.assertIn(result['message_id'], announcement.message_ids.ids)

    def test_native_readonly_channel_is_also_excluded(self):
        readonly = self.env.ref('nodo_base.channel_sales_quotes')
        readonly.write({'is_readonly': True})
        self.assertFalse(readonly.with_user(self.seller).can_self_edit_readonly_channel)
        self.assertEqual(self.service.search_share_targets('channel', '销售报价'), [])
        with self.assertRaisesRegex(AccessError, '频道为只读'):
            self.service.share_record('sale.order', self.quote.id, 'channel', readonly.id)
