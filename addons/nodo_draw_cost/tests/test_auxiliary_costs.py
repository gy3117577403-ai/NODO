from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.nodo_draw_cost import auxiliary_rules as rules


@tagged('nodo', 'post_install', '-at_install')
class TestAuxiliaryCosts(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engineer = new_test_user(cls.env, login='aux.engineer@nodo.test', groups='nodo_base.group_role_engineering')
        cls.sales = new_test_user(cls.env, login='aux.sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.costing = new_test_user(cls.env, login='aux.costing@nodo.test', groups='nodo_base.group_role_costing')
        cls.designs = cls.env['nodo.draw.design']
        cls.book = cls.env['nodo.cost.auxiliary.price']
        cls.sample = dict(source='AE-AUX', title='双开门基础柜', kind='double', width=1000, height=700, depth=300,
                          quantity=3, lines=[])
        design_id = cls.designs.handoff_bom(cls.sample)['design_id']
        cls.design = cls.designs.with_user(cls.engineer).browse(design_id)
        old_values = {rules.HINGE: 2, rules.RING: 1.6, rules.SEAL: 3.5, '30102000002': 5.2,
                      '30104000002': 9, '30199000155': 5.8, '30199000156': 5.8}
        for code, price in old_values.items():
            name, unit, by_material = rules.ITEMS[code]
            cls.book.create(dict(code=code, name=name, unit=unit, price_per_unit=price,
                                 variant='steel' if by_material else 'common'))
        cls.extra = cls.book.create(dict(code='AUX-EARTH', name='接地编织带', price_per_unit=2.5, scope='double'))
        cls.stripe = cls.book.create(dict(code='AUX-METRE', name='防护条', price_per_unit=2.5, unit='metre'))

    def calculation(self, **spec):
        return self.design.preview_auxiliary_costs(spec)

    def save(self, items=(), lock=None, revision=0):
        draft = dict(items=[dict(id=rate.id, quantity=qty) for rate, qty in items], lock=lock)
        return self.design.save_auxiliary_choices(self.design.edit_number, revision, draft)

    def test_threshold_and_companions_are_per_cabinet(self):
        for height in (700, 800):
            result = self.calculation(height=height)
            self.assertEqual(result['total'], 24.2)
            self.assertEqual(result['selected_lock'], 'MS813')
            self.assertEqual([r['quantity'] for r in result['standard']], [6, 2, 1])
            self.assertEqual(result['reference_count'], 3)
        taller = self.calculation(height=801)
        lock_codes = [row['code'] for row in taller['standard'] if row['lock_item']]
        self.assertEqual(lock_codes, list(rules.LOCKS['MS821']))
        self.assertEqual(taller['total'], 39.6)
        self.assertEqual(taller['lock_change'], dict(previous='MS813', current='MS821', difference=15.4))
        self.assertNotIn(rules.RING, [r['code'] for r in self.calculation(height=1100)['standard']])
        self.assertNotIn(rules.RING, [r['code'] for r in self.calculation(kind='single', height=1000)['standard']])
        ring = self.calculation(kind='single', height=1001)['standard'][-1]
        self.assertEqual((ring['code'], ring['quantity']), (rules.RING, 2))
        self.assertIsNone(self.calculation(height=None)['total'])

    def test_optional_preserved_and_rechecked_when_kind_changes(self):
        edit = self.design.edit_number
        initial = self.save([(self.extra, 2), (self.stripe, 1.25)])
        self.assertEqual(initial['total'], 32.33)
        self.assertEqual(initial['revision'], 1)
        self.assertEqual(self.design.edit_number, edit)
        changed = self.calculation(kind='single')
        unresolved = next(row for row in changed['optional'] if row['id'] == self.extra.id)
        self.assertEqual(unresolved['quantity'], 2)
        self.assertIn('不适用', unresolved['issue'])
        self.assertIsNone(changed['total'])
        self.extra.with_user(self.costing).price_per_unit = 3
        self.assertEqual(self.calculation()['total'], 33.33)
        with self.assertRaisesRegex(UserError, '另一窗口'):
            self.save([(self.extra, 1)])
        result = self.save([], revision=1)
        self.assertEqual(result['optional'], [])
        self.assertEqual(result['total'], 24.2)

    def test_only_matching_optional_supplies_can_be_added(self):
        hinge = self.book.search([('code', '=', rules.HINGE)])
        tall_lock = self.book.search([('code', '=', '30104000002')])
        with self.assertRaisesRegex(UserError, '整数'):
            self.save([(self.extra, 1.25)])
        with self.assertRaisesRegex(UserError, '标配条件'):
            self.save([(tall_lock, 1)])
        selected = self.save([(hinge, 2)])
        self.assertEqual(selected['total'], 28.2)
        self.assertEqual(selected['standard'][0]['quantity'], 6)
        self.assertEqual(selected['optional'][0]['quantity'], 2)
        self.assertIsNone(self.calculation(material='stainless')['total'])
        hinge.active = False
        self.assertIsNone(self.calculation()['total'])
        self.assertEqual(self.calculation()['saved']['items'], selected['saved']['items'])

    def test_picker_uses_the_current_price_and_standard_quantity(self):
        rates = {row['code']: row for row in self.calculation()['catalog']}
        self.assertEqual((rates[rules.HINGE]['standard_quantity'], rates[rules.HINGE]['price']), (6, 2))
        self.assertEqual((rates[self.extra.code]['standard_quantity'], rates[self.extra.code]['basis']), (0, 'reference'))
        self.assertEqual(rates[self.stripe.code]['measure'], 'metre')
        self.assertEqual(rates[self.extra.code]['model_status'], 'unlinked')
        self.assertNotIn('30104000002', rates)
        self.stripe.price_per_unit = 0
        unpriced = next(row for row in self.calculation()['catalog'] if row['id'] == self.stripe.id)
        self.assertIsNone(unpriced['price'])
        self.assertEqual(unpriced['basis'], '')

    def test_review_groups_take_the_unrounded_amount_and_keep_missing_rows_separate(self):
        self.stripe.price_per_unit = 0.3333
        result = self.save([(self.stripe, 0.123), (self.extra, 2)])
        self.assertEqual(result['groups'], {
            'standard': {'amount': 24.2, 'missing': 0},
            'optional': {'amount': 5.04, 'missing': 0},
        })
        self.assertEqual(result['exact_subtotal'], '29.2409959')
        fact = next(row for row in result['optional'] if row['id'] == self.stripe.id)
        self.assertEqual((fact['rate_id'], fact['model_status']), (self.stripe.id, 'unlinked'))

        self.extra.price_per_unit = 0
        unresolved = self.calculation()
        self.assertEqual(unresolved['groups']['optional'], {'amount': 0.04, 'missing': 1})
        self.assertIsNone(unresolved['total'])
        self.assertEqual(unresolved['known_subtotal'], 24.24)

        hinge = self.book.search([('code', '=', rules.HINGE)])
        hinge.price_per_unit = 2.001
        self.stripe.price_per_unit = 0.005
        rounded = self.design.preview_auxiliary_costs(None, dict(
            items=[dict(id=self.stripe.id, quantity=1)], lock=None,
        ))
        self.assertEqual((rounded['groups']['standard']['amount'], rounded['groups']['optional']['amount']), (24.21, 0.01))
        self.assertEqual((rounded['total'], rounded['rounding_difference']), (24.21, -0.01))

    def test_lock_override_requires_basis_and_revalidation_on_spec_change(self):
        lock = dict(scheme='MS821', reason='', confirm=True)
        with self.assertRaisesRegex(UserError, '换配依据'):
            self.save(lock=lock)
        lock['reason'] = '项目指定大锁与配套锁杆'
        changed = self.save(lock=lock)
        self.assertEqual(changed['total'], 39.6)
        self.assertEqual(changed['selected_lock'], 'MS821')
        self.assertEqual(changed['standard'][-1]['condition'], '技术确认换配')
        self.assertEqual(self.design.auxiliary_choices['lock']['confirmed_by'], self.engineer.id)
        after_change = self.calculation(width=1001)
        self.assertTrue(after_change['lock_pending'])
        self.assertEqual(after_change['selected_lock'], 'MS813')
        self.assertIsNone(after_change['total'])
        reverted = self.save(revision=1)
        self.assertEqual(reverted['total'], 24.2)

    def test_handoff_match_and_missing_price_do_not_guess_supply(self):
        parameters = dict(self.sample, source='AUX-BOM', lines=[
            dict(code=rules.HINGE, quantity=6), dict(code='30209000002', name='AE 箱铰链管', quantity=6),
        ])
        test_id = self.designs.handoff_bom(parameters)['design_id']
        result = self.designs.with_user(self.engineer).browse(test_id).preview_auxiliary_costs()
        self.assertEqual(result['known_subtotal'], 24.2)
        self.assertIsNone(result['total'])
        self.assertEqual([(row['code'], row['issue']) for row in result['optional']], [('30209000002', '待补价')])

    def test_roles_and_company_scope(self):
        company = self.env['res.company'].create(dict(name='其他板料企业'))
        other = new_test_user(self.env, login='aux.other@nodo.test', groups='nodo_base.group_role_engineering',
                              company_id=company.id, company_ids=[Command.set([company.id])])
        foreign = self.book.create(dict(company_id=company.id, code='AUX-OTHER', name='其他辅材', price_per_unit=2))
        with self.assertRaises(AccessError):
            self.design.with_user(self.sales).preview_auxiliary_costs()
        with self.assertRaises(AccessError):
            self.design.with_user(other).preview_auxiliary_costs()
        with self.assertRaisesRegex(UserError, '查无'):
            self.save([(foreign, 1)])
        with self.assertRaises(AccessError):
            self.extra.with_user(self.engineer).write(dict(price_per_unit=2))
