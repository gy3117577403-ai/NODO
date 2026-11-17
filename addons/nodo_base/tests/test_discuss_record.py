from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussRecord(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = new_test_user(cls.env, login='card_reader@nodo.test')
        cls.other = new_test_user(cls.env, login='card_other@nodo.test')
        cls.admin = cls.env.ref('base.user_admin')
        cls.service = cls.env['nodo.discuss.record'].with_user(cls.reader)

    def test_fallback_card_only_contains_model_and_record_name(self):
        partner = self.env['res.partner'].create({'name': '协作联系人', 'active': False})
        reference = {'model': partner._name, 'id': partner.id}
        model_label = self.env['ir.model']._get(partner._name).name
        self.assertEqual(self.service.get_record_cards([reference, reference]), [{
            **reference, 'title': f'{model_label} {partner.name}',
            'subtitle': '', 'status': '', 'status_type': '',
        }])
        if 'sale.order' not in self.env:
            self.assertEqual(self.service.get_record_card_types(), [])

    def test_batch_omits_unreadable_missing_and_invalid_records(self):
        channels = self.env['discuss.channel']
        visible = channels._create_group(self.reader | self.other, name='可见群聊')
        hidden = channels._create_group(self.admin | self.other, name='私有群聊')
        self.assertTrue(visible.with_user(self.reader).has_access('read'))
        self.assertFalse(hidden.with_user(self.reader).has_access('read'))
        hidden_parameter = self.env['ir.config_parameter'].search([], limit=1)
        self.assertFalse(hidden_parameter.with_user(self.reader).has_access('read'))
        deleted = channels._create_group(self.reader | self.other, name='已删除群聊')
        deleted_id = deleted.id
        deleted.unlink()

        refs = [
            {'model': channels._name, 'id': hidden.id},
            {'model': hidden_parameter._name, 'id': hidden_parameter.id},
            {'model': channels._name, 'id': deleted_id},
            {'model': 'nodo.missing.model', 'id': 1},
            {'model': channels._name, 'id': True},
            {'model': channels._name, 'id': visible.id},
        ]
        self.assertEqual(self.service.get_record_cards(refs[:-1]), [])
        cards = self.service.get_record_cards(refs)
        self.assertEqual([(card['model'], card['id']) for card in cards], [(channels._name, visible.id)])

    def test_portal_cannot_fetch_cards_or_reference_types(self):
        portal = new_test_user(
            self.env, login='card_portal@nodo.test', groups='base.group_portal', notification_type='email',
        )
        service = self.service.with_user(portal)
        reference = {'model': 'res.partner', 'id': portal.partner_id.id}
        self.assertEqual(service.get_record_cards([reference]), [])
        self.assertEqual(service.get_record_card_types(), [])
