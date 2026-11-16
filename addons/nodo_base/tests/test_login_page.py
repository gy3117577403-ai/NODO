import re

from odoo.tests import HttpCase, tagged


def visible_text(html):
    html = re.sub(r'(?is)<(script|style|template)\b.*?</\1>', ' ', html)
    html = re.sub(r'(?s)<!--.*?-->', ' ', html)
    text = re.sub(r'(?s)<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', text)


@tagged('nodo', 'post_install', '-at_install')
class TestNodoLoginPage(HttpCase):

    def setUp(self):
        super().setUp()
        # 测试期间开发库和测试库同时存在，需指定数据库，否则会进入数据库选择页
        response = self.url_open(f'/web/login?db={self.env.cr.dbname}')
        self.assertEqual(response.status_code, 200)
        self.html = response.text

    def test_title_and_favicon(self):
        self.assertRegex(self.html, r'<title>\s*NODO\s*</title>')
        self.assertIn('/nodo_base/static/img/favicon.svg', self.html)
        self.assertNotIn('/web/static/img/favicon.ico', self.html)

    def test_visible_text_is_nodo_only(self):
        text = visible_text(self.html)
        self.assertIn('NODO', text)
        self.assertNotIn('odoo', text.lower(), text[:300])

    def test_no_database_manager_or_promotion_links(self):
        self.assertNotIn('/web/database/manager', self.html)
        self.assertNotIn('www.odoo.com', self.html)
        self.assertNotIn('Powered by', self.html)

    def test_wordmark_and_layout(self):
        # 正常打开登录页时播放动画（没有 o_nodo_wm_static）
        self.assertIn('class="o_nodo_wm"', self.html)
        self.assertIn('o_nodo_login_card', self.html)
        self.assertIn('o_nodo_login_bg', self.html)
        self.assertIn('登录', visible_text(self.html))

    def test_click_to_replay_script(self):
        # 点击字标重播：脚本存在，且没有被转义成 &amp;（会导致脚本语法错误）
        self.assertIn('o_nodo_wm_reset', self.html)
        script = self.html[self.html.index('o_nodo_wm_reset') - 1500:self.html.index('o_nodo_wm_reset') + 300]
        self.assertNotIn('&amp;', script)

    def test_signup_and_reset_password_disabled(self):
        # 首次安装时关闭自助注册和邮件重置密码，登录页改为提示联系管理员
        self.assertNotIn('/web/signup', self.html)
        self.assertNotIn('/web/reset_password', self.html)
        self.assertIn('忘记密码请联系管理员', self.html)

    def test_environment_badge(self):
        ICP = self.env['ir.config_parameter'].sudo()
        self.assertNotIn('o_nodo_env_badge', self.html)
        ICP.set_str('nodo.environment', 'test')
        html = self.url_open(f'/web/login?db={self.env.cr.dbname}').text
        self.assertIn('测试环境', html)
        ICP.set_str('nodo.environment', 'prod')
        html = self.url_open(f'/web/login?db={self.env.cr.dbname}').text
        self.assertNotIn('o_nodo_env_badge', html)

    def test_default_company_logo_route_serves_nodo_wordmark(self):
        company = self.env.company
        self.assertTrue(company.uses_default_logo)
        response = self.url_open(f'/logo.png?company={company.id}&db={self.env.cr.dbname}')
        self.assertEqual(response.status_code, 200)
        with open(self._nodo_logo_path(), 'rb') as fh:
            self.assertEqual(response.content, fh.read())

    def _nodo_logo_path(self):
        from odoo.tools.misc import file_path
        return file_path('nodo_base/static/img/nodo-wordmark.png')

    def test_webmanifest_uses_nodo_icons(self):
        manifest = self.url_open(f'/web/manifest.webmanifest?db={self.env.cr.dbname}').json()
        self.assertEqual(manifest['name'], 'NODO')
        self.assertEqual(manifest['theme_color'], '#1F4F46')
        self.assertTrue(manifest['icons'])
        for icon in manifest['icons']:
            self.assertTrue(icon['src'].startswith('/nodo_base/static/img/'), icon)
