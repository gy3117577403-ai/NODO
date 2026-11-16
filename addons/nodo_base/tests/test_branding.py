from lxml import etree

from odoo.tests import TransactionCase, tagged

from odoo.addons.nodo_base.models.res_company import NODO_BOT_NAME, NODO_PRIMARY


@tagged('nodo', 'post_install', '-at_install')
class TestNodoBranding(TransactionCase):

    def test_web_app_name(self):
        self.assertEqual(self.env['ir.config_parameter'].sudo().get_str('web.web_app_name'), 'NODO')

    def test_new_company_uses_nodo_email_color(self):
        company = self.env['res.company'].create({'name': 'NODO 测试分公司'})
        self.assertEqual(company.email_secondary_color, NODO_PRIMARY)

    def test_apply_branding_keeps_custom_colors(self):
        upstream = self.env['res.company'].create({'name': '上游色公司', 'email_secondary_color': '#875A7B'})
        custom = self.env['res.company'].create({'name': '自定义色公司', 'email_secondary_color': '#123456'})
        self.env['res.company']._nodo_apply_branding()
        self.assertEqual(upstream.email_secondary_color, NODO_PRIMARY)
        self.assertEqual(custom.email_secondary_color, '#123456')

    def test_bot_renamed(self):
        self.assertEqual(self.env.ref('base.partner_root').name, NODO_BOT_NAME)

    def test_enterprise_settings_hidden(self):
        # 用 _get_view 取合并后、按用户权限裁剪前的视图，确保能看到全部推广字段
        root, _view = self.env['res.config.settings']._get_view(view_type='form')
        upgrade_fields = root.xpath("//field[@widget='upgrade_boolean']")
        self.assertTrue(upgrade_fields, '设置页应包含企业版推广字段，否则本测试失去意义')
        for field in upgrade_fields:
            setting = next(field.iterancestors('setting'), None)
            target = setting if setting is not None else field
            self.assertEqual(target.get('invisible'), '1', etree.tostring(target)[:200])

    def test_apps_action_hides_enterprise_placeholders(self):
        action = self.env.ref('base.open_module_tree')
        self.assertIn('to_buy', action.domain or '')

    def test_mail_footers_without_upstream_promotion(self):
        for xmlid in ('mail.mail_notification_layout', 'mail.mail_notification_light'):
            arch = self.env.ref(xmlid).get_combined_arch()
            self.assertNotIn('Powered by', arch, xmlid)
            self.assertNotIn('odoo.com', arch, xmlid)
            self.assertIn('mail_unfollow', arch, xmlid)

    def test_backend_patches_in_asset_bundle(self):
        Asset = self.env['ir.asset']
        params = Asset._get_asset_params()
        backend = [p[0] for p in Asset._get_asset_paths('web.assets_backend', params)]
        for suffix in (
            'nodo_base/static/src/js/user_menu_patch.js',
            'nodo_base/static/src/js/error_dialog_patch.js',
            'nodo_base/static/src/xml/res_config_edition.xml',
        ):
            self.assertTrue(any(p.endswith(suffix) for p in backend), suffix)
        primary = [p[0] for p in Asset._get_asset_paths('web._assets_primary_variables', params)]
        self.assertTrue(primary, '主变量资源包为空')
        self.assertTrue(primary[0].endswith('nodo_base/static/src/scss/primary_variables.scss'), primary[:3])
