from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import BinaryBytes
from odoo.tools.misc import file_open

from odoo.addons.nodo_base.models.res_company import UPSTREAM_BOT_IMAGE
from odoo.addons.nodo_base.models.res_partner import NODO_AVATAR_COLORS


def _content(value):
    value = getattr(value, 'content', value)
    return bytes(value) if value else b''


@tagged('nodo', 'post_install', '-at_install')
class TestNodoDiscuss(TransactionCase):

    def test_new_users_get_inbox_notifications(self):
        user = new_test_user(self.env, login='discuss_inbox@nodo.test', groups='nodo_base.group_role_sales')
        self.assertEqual(user.notification_type, 'inbox')

    def test_existing_internal_users_switched_on_install(self):
        user = new_test_user(self.env, login='discuss_email@nodo.test', groups='base.group_user', notification_type='email')
        self.env['res.users']._nodo_use_inbox_notifications()
        self.assertEqual(user.notification_type, 'inbox')

    def test_upstream_bot_onboarding_disabled(self):
        user = new_test_user(self.env, login='discuss_bot@nodo.test', groups='base.group_user')
        channel = user._init_odoobot()
        self.assertFalse(channel)
        self.assertEqual(user.odoobot_state, 'disabled')

    def test_bot_avatar_replaced(self):
        bot = self.env.ref('base.partner_root')
        with file_open(UPSTREAM_BOT_IMAGE, 'rb') as fh:
            upstream = fh.read()
        self.assertNotEqual(_content(bot.image_1920), upstream)

    def test_generated_avatar_uses_nodo_palette_and_follows_rename(self):
        partner = self.env['res.partner'].create({'name': '测试甲'})
        svg = _content(partner._avatar_generate_svg()).decode()
        self.assertTrue(any(color in svg for color in NODO_AVATAR_COLORS), svg[:200])
        partner.image_1920 = partner._avatar_generate_svg()
        self.assertTrue(partner._nodo_has_generated_avatar())
        partner.name = '销售乙'
        # 自动生成的头像在改名后清空，由系统按新名字即时生成
        self.assertFalse(partner.image_1920)
        self.assertIn('销', _content(partner.avatar_128).decode())

    def test_uploaded_avatar_kept_on_rename(self):
        with file_open('nodo_base/static/img/nodo-icon-192.png', 'rb') as fh:
            png = fh.read()
        partner = self.env['res.partner'].create({'name': '上传头像', 'image_1920': BinaryBytes(png, filename='avatar.png')})
        self.assertFalse(partner._nodo_has_generated_avatar())
        partner.name = '上传头像改名'
        self.assertTrue(partner.image_1920)

    def test_all_employees_channel_renamed(self):
        channel = self.env.ref('mail.channel_all_employees', raise_if_not_found=False)
        if channel:
            self.assertEqual(channel.name, '全员通知')

    def test_channel_avatar_uses_nodo_palette(self):
        channel = self.env['discuss.channel'].create({'name': '生产调度', 'channel_type': 'channel'})
        svg = _content(channel._generate_avatar()).decode()
        self.assertTrue(any(color in svg for color in NODO_AVATAR_COLORS), svg[:200])
        self.assertIn('生', svg)

    def test_discuss_assets_in_backend_bundle(self):
        Asset = self.env['ir.asset']
        paths = [p[0] for p in Asset._get_asset_paths('web.assets_backend', Asset._get_asset_params())]
        for suffix in (
            'nodo_base/static/src/js/discuss_patch.js',
            'nodo_base/static/src/js/discuss_people.js',
            'nodo_base/static/src/js/discuss_channels.js',
            'nodo_base/static/src/js/record_cards.js',
            'nodo_base/static/src/js/share_record.js',
            'nodo_base/static/src/xml/discuss.xml',
            'nodo_base/static/src/xml/discuss_people.xml',
            'nodo_base/static/src/xml/discuss_channels.xml',
            'nodo_base/static/src/xml/record_cards.xml',
            'nodo_base/static/src/xml/share_record.xml',
            'nodo_base/static/src/scss/discuss.scss',
            'nodo_base/static/src/scss/material.scss',
        ):
            self.assertTrue(any(p.endswith(suffix) for p in paths), suffix)


@tagged('nodo', 'post_install', '-at_install')
class TestNodoChatPeople(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        cls.viewer = new_test_user(env, login='chat_viewer@nodo.test', name='陈宁')
        cls.no_role = new_test_user(env, login='chat_no_role@nodo.test', name='周禾')
        cls.sales = new_test_user(
            env, login='chat_sales@nodo.test', name='林澄', groups='nodo_base.group_role_sales',
        )
        cls.multi_role = new_test_user(
            env, login='chat_multi_role@nodo.test', name='叶青',
            groups='nodo_base.group_role_sales,nodo_base.group_role_purchase',
        )
        cls.portal = new_test_user(
            env, login='chat_portal@nodo.test', name='外部门户',
            groups='base.group_portal', notification_type='email',
        )
        cls.directory = cls.env['res.partner'].with_user(cls.viewer)

    def test_roles_follow_chat_people_in_store(self):
        result = self.directory.nodo_search_chat_people()
        people = {p['id']: p for p in result['store_data']._build_result()['res.partner']}
        person = people[self.multi_role.partner_id.id]
        self.assertEqual(person['name'], '叶青')
        self.assertEqual(person['nodo_chat_roles'], ['销售', '采购'])
        self.assertEqual(people[self.no_role.partner_id.id]['nodo_chat_roles'], [])
        self.assertTrue(person['avatar_128_access_token'])
        self.assertEqual(person['main_user_id'], self.multi_role.id)
        self.assertNotIn('email', person)
        self.assertNotIn('phone', person)
        self.assertEqual(
            [option['label'] for option in result['role_options']],
            ['销售', '核算', '批准', '技术', '采购', '生产', '车间操作', '质检'],
        )

    def test_chat_people_excludes_bot_archived_portal_and_external_contacts(self):
        archived = new_test_user(
            self.env, login='chat_archived@nodo.test', name='停用同事',
            groups='nodo_base.group_role_sales', context={'no_reset_password': True},
        )
        archived.active = False
        external = self.env['res.partner'].create({'name': '外部联系人'})
        bot = self.env.ref('base.partner_root')
        # The assistant remains excluded even when its contact has an active internal account.
        new_test_user(
            self.env, login='chat_bot_account@nodo.test', partner_id=bot.id, name=bot.name,
            context={'no_reset_password': True},
        )
        for partner in bot | archived.partner_id | self.portal.partner_id | external | self.viewer.partner_id:
            with self.subTest(partner=partner.name):
                result = self.directory.nodo_search_chat_people(search_term=partner.name)
                self.assertNotIn(partner.id, result['partner_ids'])

    def test_chat_people_search_combines_role_and_name_or_role_term(self):
        archived = new_test_user(
            self.env, login='chat_sales_archive@nodo.test',
            partner_id=self.no_role.partner_id.id, name=self.no_role.name,
            groups='nodo_base.group_role_sales', context={'no_reset_password': True},
        )
        archived.active = False
        search = self.directory.nodo_search_chat_people
        sales = self.sales.partner_id.id
        multi = self.multi_role.partner_id.id
        self.assertCountEqual(search(search_term='销售')['partner_ids'], [sales, multi])
        self.assertEqual(search(role='purchase')['partner_ids'], [multi])
        self.assertEqual(search(search_term='销售', role='purchase')['partner_ids'], [multi])
        self.assertEqual(search(search_term='叶', role='purchase')['partner_ids'], [multi])
        self.assertFalse(search(search_term='林', role='purchase')['partner_ids'])
        self.assertFalse(search(search_term='chat_sales@nodo.test')['partner_ids'])

    def test_portal_and_public_do_not_receive_roles(self):
        for viewer in self.portal | self.env.ref('base.public_user'):
            with self.subTest(user=viewer.id):
                with self.assertRaises(AccessError):
                    self.directory.with_user(viewer).nodo_search_chat_people(search_term='销售')
                # Channel members can serialize their accessible partners with sudo. The Store
                # still gates roles on the recipient, including when those records are sudoed.
                partner = self.multi_role.partner_id.with_user(viewer).sudo()
                people = Store().add(partner, '_store_partner_fields')._build_result()['res.partner']
                self.assertEqual(people[0]['name'], '叶青')
                self.assertNotIn('nodo_chat_roles', people[0])

    def test_group_store_members_have_roles_and_directory_excludes_existing_members(self):
        group = self.env['discuss.channel'].with_user(self.viewer)._create_group(
            self.viewer | self.sales | self.multi_role,
        )
        data = Store().add(group.channel_member_ids, '_store_member_fields')._build_result()
        roles = {p['id']: p['nodo_chat_roles'] for p in data['res.partner']}
        self.assertEqual(roles[self.sales.partner_id.id], ['销售'])
        self.assertEqual(roles[self.multi_role.partner_id.id], ['销售', '采购'])
        self.assertEqual(roles[self.viewer.partner_id.id], [])
        self.assertFalse(self.directory.nodo_search_chat_people(role='sales', channel_id=group.id)['partner_ids'])
        with self.assertRaises(AccessError):
            self.directory.with_user(self.no_role).nodo_search_chat_people(channel_id=group.id)
