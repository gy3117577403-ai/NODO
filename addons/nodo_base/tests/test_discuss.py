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
            'nodo_base/static/src/js/record_cards.js',
            'nodo_base/static/src/xml/discuss.xml',
            'nodo_base/static/src/xml/record_cards.xml',
            'nodo_base/static/src/scss/discuss.scss',
            'nodo_base/static/src/scss/material.scss',
        ):
            self.assertTrue(any(p.endswith(suffix) for p in paths), suffix)
