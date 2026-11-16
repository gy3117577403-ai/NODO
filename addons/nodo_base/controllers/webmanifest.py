from odoo.addons.web.controllers.webmanifest import WebManifest

NODO_ICONS = [
    ('192x192', '/nodo_base/static/img/nodo-icon-192.png'),
    ('512x512', '/nodo_base/static/img/nodo-icon-512.png'),
]


class NodoWebManifest(WebManifest):
    """安装为网页应用时使用 NODO 图标（名称由系统参数 web.web_app_name 控制）。"""

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        manifest['background_color'] = '#F7FAF9'
        manifest['theme_color'] = '#1F4F46'
        manifest['icons'] = [
            {'src': src, 'sizes': size, 'type': 'image/png'}
            for size, src in NODO_ICONS
        ]
        return manifest

    def _icon_path(self):
        return 'nodo_base/static/img/nodo-icon-192.png'
