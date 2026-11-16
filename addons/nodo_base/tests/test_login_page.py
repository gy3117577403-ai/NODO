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

    def test_wordmark_and_layout_class(self):
        self.assertIn('o_nodo_wordmark', self.html)
        self.assertIn('o_nodo_login', self.html)
