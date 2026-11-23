from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestAuxiliaryPrice(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.costing = new_test_user(cls.env, login='aux.book@nodo.test', groups='nodo_base.group_role_costing')
        cls.book = cls.env['nodo.cost.auxiliary.price'].with_user(cls.costing)

    def test_prices_can_change_while_purchasing_identity_stays_fixed(self):
        row = self.book.create(dict(code=' aux-001 ', name='接地带', price_per_unit=2.5))
        self.assertEqual(row.code, 'AUX-001')
        row.write(dict(price_per_unit=3.25, basis='business'))
        self.assertEqual(row.price_per_unit, 3.25)
        with self.assertRaises(ValidationError):
            row.write(dict(unit='metre'))
        row.active = False
        with self.assertRaises(IntegrityError):
            self.book.create(dict(code='aux-001', name='接地带'))
        row.active = True
        with self.assertRaises(IntegrityError):
            self.book.create(dict(code='AUX-002', name='接地带', price_per_unit=-1))

    def test_costing_cannot_create_for_an_unavailable_company(self):
        foreign = self.env['res.company'].create(dict(name='辅材核对乙'))
        with self.assertRaises(AccessError):
            self.book.create(dict(code='AUX-003', name='接地带', company_id=foreign.id))
