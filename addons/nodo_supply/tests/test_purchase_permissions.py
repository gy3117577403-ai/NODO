from odoo.fields import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestPurchasePermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.assistant = new_test_user(
            cls.env, login='supply_assistant@nodo.test',
            groups='nodo_supply.group_purchase_assistant,base.group_allow_export',
        )
        cls.buyer = new_test_user(
            cls.env, login='supply_buyer@nodo.test',
            groups='nodo_supply.group_purchase_buyer,base.group_allow_export',
        )
        cls.manager = new_test_user(
            cls.env, login='supply_manager@nodo.test', groups='nodo_supply.group_purchase_manager',
        )
        cls.engineer = new_test_user(
            cls.env, login='supply_engineer@nodo.test', groups='nodo_base.group_role_engineering',
        )
        cls.colleague = new_test_user(cls.env, login='supply_colleague@nodo.test')
        cls.vendor = cls.env['res.partner'].create({'name': '雾岬物资'})
        cls.product = cls.env['product.product'].create({
            'name': '配线标识加工', 'type': 'service', 'purchase_ok': True, 'sale_ok': False,
        })
        cls.purchase = cls.env['purchase.order']
        cls.cards = cls.env['nodo.discuss.record']

    def _draft_values(self, price=87.25):
        line = {'product_id': self.product.id, 'product_qty': 3}
        if price is not None:
            line['price_unit'] = price
        return {'partner_id': self.vendor.id, 'order_line': [Command.create(line)]}

    def _draft(self, user, **values):
        return self.purchase.with_user(user).create({**self._draft_values(), **values})

    def _purchase_card(self, order, user):
        return self.cards.with_user(user).get_record_cards([{'model': 'purchase.order', 'id': order.id}])

    def test_both_purchasing_roles_can_create_edit_and_confirm(self):
        for user in (self.buyer, self.manager):
            with self.subTest(user=user.login):
                order = self._draft(user)
                order.order_line.write({'product_qty': 4})
                order.write({'partner_ref': 'BX-4'})
                order.button_confirm()
                self.assertEqual(order.state, 'purchase')
                self.assertEqual(order.order_line.product_qty, 4)

    def test_nodo_confirmation_reuses_native_stock_flow_in_one_step(self):
        self.company.write({
            'po_double_validation': 'two_step', 'po_double_validation_amount': 1,
        })
        material = self.env['product.product'].create({'name': '护线端盖', 'type': 'consu', 'purchase_ok': True})
        order = self.purchase.with_user(self.buyer).create({
            'partner_id': self.vendor.id,
            'order_line': [Command.create({'product_id': material.id, 'product_qty': 2, 'price_unit': 9})],
        })
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')
        self.assertTrue(order.sudo().picking_ids)

    def test_assistant_only_reads_price_of_own_current_draft(self):
        order = self._draft(self.assistant)
        other = self._draft(self.buyer, nodo_technical_user_id=self.assistant.id)
        self.assertEqual(order.order_line.read(['price_unit'])[0]['price_unit'], 87.25)
        self.assistant.write({'nodo_purchase_review': 'allow'})
        self.assertEqual(self._purchase_card(other, self.assistant), [])
        with self.assertRaises(AccessError):
            other.with_user(self.assistant).action_nodo_review_specs()
        self.assertTrue(self._purchase_card(order, self.assistant))
        self.assertTrue(order.export_data(['amount_total'])['datas'])
        with self.assertRaisesRegex(AccessError, '最终确认'):
            order.button_confirm()
        with self.assertRaises(AccessError):
            order.write({'state': 'purchase'})
        order.with_user(self.buyer).button_confirm()
        self.assertEqual(order.sudo().state, 'purchase')
        with self.assertRaises(AccessError):
            order.read(['amount_total'])
        with self.assertRaises(AccessError):
            order.export_data(['amount_total'])
        self.assertEqual(self._purchase_card(order, self.assistant), [])

    def test_technical_review_is_assigned_and_cleared_after_spec_edit(self):
        order = self._draft(self.assistant)
        not_assigned = self._draft(self.buyer)
        buyer_order = order.with_user(self.buyer)
        buyer_order.write({'nodo_technical_user_id': self.engineer.id})
        engineer_order = order.with_user(self.engineer)
        self.assertTrue(engineer_order.read(['amount_total'])[0]['amount_total'])
        self.assertEqual(engineer_order.order_line.price_unit, 87.25)
        self.assertEqual(self._purchase_card(not_assigned, self.engineer), [])
        with self.assertRaises(AccessError):
            engineer_order.write({'partner_ref': 'RF-1'})
        with self.assertRaises(AccessError):
            engineer_order.order_line.write({'product_qty': 5})
        with self.assertRaisesRegex(AccessError, '最终确认'):
            engineer_order.button_confirm()
        engineer_order.action_nodo_review_specs()
        self.assertEqual(engineer_order.nodo_reviewed_by_id.id, self.engineer.id)
        self.assertTrue(engineer_order.nodo_reviewed_at)
        buyer_order.order_line.write({'product_qty': 8})
        self.assertFalse(engineer_order.nodo_reviewed_at)
        buyer_order.button_confirm()
        self.assertEqual(engineer_order.state, 'purchase')

    def test_personal_deny_covers_combined_roles_and_native_permission(self):
        operator = new_test_user(
            self.env, login='supply_combined@nodo.test',
            groups='nodo_supply.group_purchase_buyer,nodo_base.group_role_engineering,purchase.group_purchase_user',
        )
        order = self._draft(self.assistant).with_user(operator)
        operator.write({'nodo_purchase_confirm': 'deny'})
        with self.assertRaisesRegex(AccessError, '最终确认'):
            order.button_confirm()
        with self.assertRaisesRegex(AccessError, '最终确认'):
            order.button_approve()
        with self.assertRaises(AccessError):
            order.write({'state': 'purchase'})
        self.assertEqual(order.state, 'draft')
        operator.write({'nodo_purchase_confirm': 'inherit', 'nodo_purchase_draft': 'deny'})
        with self.assertRaises(AccessError):
            order.write({'partner_ref': 'RF-3'})
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')
        logs = operator.nodo_permission_change_ids.filtered(lambda log: log.permission_name == '确认采购单')
        self.assertEqual(logs.mapped('new_mode'), ['inherit', 'deny'])
        self.assertEqual(logs.create_uid, self.env.user)
        self.assertEqual(logs.company_id, operator.company_id)

    def test_employee_cannot_change_personal_settings(self):
        own_user = self.assistant.with_user(self.assistant)
        for user in (own_user, own_user.sudo()):
            with self.assertRaisesRegex(AccessError, '只有系统管理员'):
                user.write({'nodo_purchase_confirm': 'allow'})
        self.assertEqual(self.assistant.nodo_purchase_confirm, 'inherit')

    def test_price_deny_covers_fields_export_report_and_card(self):
        order = self._draft(self.buyer)
        lines = order.order_line
        self.assertEqual(lines.price_unit, 87.25)
        self.buyer.write({'nodo_purchase_price': 'deny'})
        self.assertEqual(order.read(['name'])[0]['name'], order.name)
        self.assertNotIn('amount_total', order.fields_get())
        self.assertNotIn('price_unit', lines.fields_get())
        for records, field in ((order, 'amount_total'), (lines, 'price_unit')):
            with self.assertRaises(AccessError):
                records.read([field])
            with self.assertRaises(AccessError):
                records.export_data([field])
            with self.assertRaises(AccessError):
                records.search([('id', 'in', records.ids), (field, '>', 0)])
            with self.assertRaises(AccessError):
                records._read_group([('id', 'in', records.ids)], [], [f'{field}:sum'])
        with self.assertRaises(AccessError):
            self.env['ir.actions.report'].with_user(self.buyer)._render_qweb_html(
                'purchase.report_purchasequotation', [order.id],
            )
        [card] = self._purchase_card(order, self.buyer)
        self.assertEqual(card['subtitle'], self.vendor.name)
        self.assertNotIn('87.25', order.with_context(show_total_amount=True).display_name)
        self.assertNotIn('87.25', lines.with_context(display_order_name=True, formatted_display_name=True).display_name)
        self.assertNotIn('price_unit', order.get_view(view_type='form')['arch'])
        order.button_confirm()
        self.assertEqual(order.state, 'purchase')

    def test_price_deny_still_allows_price_blind_draft_editing(self):
        self.assistant.write({'nodo_purchase_price': 'deny'})
        order = self.purchase.with_user(self.assistant).create(self._draft_values(price=None))
        order.order_line.write({'product_qty': 5})
        self.assertEqual(order.order_line.product_qty, 5)
        with self.assertRaises(AccessError):
            order.order_line.write({'price_unit': 123})

    def test_personal_review_grant_still_requires_assignment(self):
        self.colleague.write({'nodo_purchase_view': 'allow', 'nodo_purchase_review': 'allow'})
        assigned = self._draft(self.buyer, nodo_technical_user_id=self.colleague.id).with_user(self.colleague)
        other = self._draft(self.buyer).with_user(self.colleague)
        assigned.action_nodo_review_specs()
        self.assertEqual(assigned.nodo_reviewed_by_id.id, self.colleague.id)
        with self.assertRaises(AccessError):
            other.action_nodo_review_specs()
        with self.assertRaises(AccessError):
            assigned.read(['amount_total'])

    def test_purchase_scope_remains_inside_allowed_companies(self):
        foreign = self.env['res.company'].create({'name': '松涧工场'})
        with self.assertRaisesRegex(AccessError, '该公司'):
            self.purchase.with_user(self.buyer).create({**self._draft_values(), 'company_id': foreign.id})
        outside = self.purchase.sudo().with_company(foreign).create({'partner_id': self.vendor.id})
        with self.assertRaises(AccessError):
            outside.with_user(self.buyer).read(['name'])
        self.assertEqual(self._purchase_card(outside, self.buyer), [])

    def test_view_deny_revokes_form_card_and_operations(self):
        order = self._draft(self.buyer)
        self.buyer.write({'nodo_purchase_view': 'deny'})
        with self.assertRaises(AccessError):
            order.read(['name'])
        with self.assertRaises(AccessError):
            order.button_confirm()
        self.assertEqual(self._purchase_card(order, self.buyer), [])

    def test_personal_view_setting_updates_the_menu(self):
        menus = self.env['ir.ui.menu'].with_user(self.colleague)
        menu = self.env.ref('nodo_supply.menu_supply_root')
        self.assertNotIn(menu.id, menus.load_menus_root()['all_menu_ids'])
        self.colleague.write({'nodo_purchase_view': 'allow'})
        self.assertIn(menu.id, menus.load_menus_root()['all_menu_ids'])
        self.colleague.write({'nodo_purchase_view': 'deny'})
        self.assertNotIn(menu.id, menus.load_menus_root()['all_menu_ids'])
