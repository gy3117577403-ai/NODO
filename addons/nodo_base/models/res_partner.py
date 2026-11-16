import base64
import hashlib

from markupsafe import escape

from odoo import models
from odoo.tools import BinaryBytes

# 自动生成头像的底色：品牌绿色系，保证白字清晰（对比度均 ≥ 4.5:1）
NODO_AVATAR_COLORS = ['#1F4F46', '#2F6F62', '#3B6E8F', '#5A5F8F', '#7A5C3E', '#3E6B4F', '#6B4E71', '#4A5D63']
GENERATED_AVATAR_MARK = b'font-size="96" text-anchor="middle"'


def nodo_avatar_color(seed):
    """按种子（姓名、频道编号等）固定取一个 NODO 色板颜色。"""
    digest = hashlib.sha256(str(seed or '').encode('utf-8')).digest()
    return NODO_AVATAR_COLORS[digest[0] % len(NODO_AVATAR_COLORS)]


def nodo_text_avatar_svg(text, seed):
    initial = escape((text or '')[:1].upper())
    return BinaryBytes((
        '<?xml version="1.0" encoding="UTF-8" ?>'
        '<svg height="180" width="180" xmlns="http://www.w3.org/2000/svg">'
        f'<rect fill="{nodo_avatar_color(seed)}" height="180" width="180"/>'
        f'<text fill="#ffffff" font-size="96" text-anchor="middle" x="90" y="125" font-family="sans-serif">{initial}</text>'
        '</svg>'
    ).encode(), filename='avatar.svg')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _avatar_generate_svg(self):
        """按姓名首字生成头像，底色从 NODO 色板中按姓名固定取一个。"""
        name = self[self._avatar_name_field] or ''
        return nodo_text_avatar_svg(name, name)

    def _nodo_has_generated_avatar(self):
        """头像是否为系统按姓名自动生成的（而不是用户上传的图片）。"""
        self.ensure_one()
        raw = self.image_1920
        if not raw:
            return False
        # Odoo 20 的二进制字段值是附件对象，内容在 .content；兼容旧版本的 bytes / base64
        raw = getattr(raw, 'content', raw)
        if not raw:
            return False
        data = bytes(raw) if isinstance(raw, (bytes, bytearray)) else str(raw).encode()
        if not data.lstrip().startswith(b'<'):
            try:
                data = base64.b64decode(data)
            except ValueError:
                return False
        return data.lstrip().startswith(b'<?xml') and GENERATED_AVATAR_MARK in data

    def write(self, vals):
        # 改名后，自动生成的头像跟着换首字（清空后由系统按新名字即时生成）；用户上传的头像不动。
        if 'name' in vals and 'image_1920' not in vals:
            generated = self.filtered(lambda p: p._nodo_has_generated_avatar())
            res = super().write(vals)
            if generated:
                super(ResPartner, generated).write({'image_1920': False})
            return res
        return super().write(vals)
