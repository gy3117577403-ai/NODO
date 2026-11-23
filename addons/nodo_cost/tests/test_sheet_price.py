from psycopg2 import IntegrityError

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..materials import stock_key


@tagged('nodo', 'post_install', '-at_install')
class TestSheetPrice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.model = cls.env['nodo.cost.sheet.price']
        cls.spec = dict(category='cold_rolled', thickness_mm=1.5, price_per_kg=5)
        cls.costing = new_test_user(cls.env, login='rates.owner@nodo.test', groups='nodo_base.group_role_costing')
        cls.engineer = new_test_user(cls.env, login='rates.reader@nodo.test', groups='nodo_base.group_role_engineering')
        cls.sales = new_test_user(cls.env, login='rates.sales@nodo.test', groups='nodo_base.group_role_sales')

    def test_edit_roles_and_company_isolation(self):
        local = self.model.with_user(self.costing).create(self.spec)
        local.write({'price_per_kg': 6})
        self.assertEqual(local.with_user(self.engineer).price_per_kg, 6)
        with self.assertRaises(AccessError):
            local.with_user(self.engineer).write({'price_per_kg': 8})
        with self.assertRaises(AccessError):
            local.with_user(self.sales).read(['price_per_kg'])
        other = self.env['res.company'].create({'name': '板材核验乙'})
        foreign = self.model.create({**self.spec, 'company_id': other.id, 'price_per_kg': 20})
        self.assertNotIn(foreign.id, self.model.with_user(self.engineer).search([]).ids)
        with self.assertRaises(AccessError):
            local.write({'company_id': other.id})
        with self.assertRaises(AccessError):
            self.model.with_user(self.costing).create({**self.spec, 'company_id': other.id, 'thickness_mm': 3})

    def test_active_spec_unique_and_grade_condition_are_exact(self):
        rate = self.model.create({**self.spec, 'grade': 'DC01', 'supply_condition': 'A'})
        with self.assertRaises(IntegrityError):
            self.model.create({**self.spec, 'grade': ' dc01 ', 'supply_condition': 'a'})
        keys = [stock_key('cold_rolled', grade, condition, gauge) for grade, condition, gauge in
                [('dc01', 'A', 1.5), (False, 'A', 1.5), ('DC01', '', 1.5), ('DC01', 'A', 1.6)]]
        self.assertEqual(self.model._rates_for(self.company, keys), {keys[0]: rate})
        rate.active = False
        replaced = self.model.create({**self.spec, 'grade': 'DC01', 'supply_condition': 'A'})
        self.assertEqual(self.model._rates_for(self.company, keys), {keys[0]: replaced})
        with self.assertRaises(IntegrityError):
            rate.active = True
        for field in ('thickness_mm', 'price_per_kg'):
            with self.subTest(field=field), self.assertRaises(IntegrityError):
                self.model.create({**self.spec, field: 0})

    def test_amounts_use_exact_row_weight_and_unrounded_sum(self):
        rate = self.model.create(self.spec)
        key = stock_key('cold_rolled', None, None, 1.5)
        rows = [dict(key=str(i), weight=weight, stock=key) for i, weight in enumerate([1.0009, 1.0009, 1.0009])]
        first = self.model._sheet_costs(self.company, rows)
        self.assertEqual(first['total'], 15.01)
        self.assertEqual(first['lines']['0']['amount'], 5.005)
        self.assertEqual(first['trial'], 3)
        rate.write(dict(price_per_kg=6, basis='business'))
        second = self.model._sheet_costs(self.company, rows)
        self.assertEqual(second['total'], 18.02)
        self.assertEqual(second['trial'], 0)
        incomplete = self.model._sheet_costs(self.company, rows + [dict(key='x', weight=2,
            stock=stock_key('galvanized', None, None, 1.5))])
        self.assertEqual(incomplete['missing'], 1)
        self.assertIsNone(incomplete['total'])
        self.assertIsNone(incomplete['lines']['x'])
