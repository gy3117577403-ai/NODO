from odoo import api, fields, models
from odoo.tools import BinaryBytes
from odoo.tools.misc import file_open

NODO_PRIMARY = '#1F4F46'
UPSTREAM_EMAIL_BUTTON_COLOR = '#875A7B'
UPSTREAM_BOT_NAME = 'OdooBot'
NODO_BOT_NAME = 'NODO 助手'
UPSTREAM_BOT_IMAGE = 'mail/static/src/img/odoobot.webp'
NODO_BOT_IMAGE = 'nodo_base/static/img/nodo-icon-512.png'


def _read_file(path):
    try:
        with file_open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


class ResCompany(models.Model):
    _inherit = 'res.company'

    # 邮件按钮和门户页面（含登录页）按钮、链接都用这个颜色，默认改为 NODO 主色。
    email_secondary_color = fields.Char(default=NODO_PRIMARY)

    @api.model
    def _nodo_apply_branding(self):
        """安装或升级时执行，只改仍是上游默认值的数据，用户自己改过的不动。

        - 公司邮件按钮色：上游默认紫色改为 NODO 主色；
        - 系统机器人联系人：上游名称改为「NODO 助手」，上游机器人头像换成 NODO 图标。
        """
        companies = self.sudo().with_context(active_test=False).search([])
        companies.filtered(
            lambda c: (c.email_secondary_color or '').upper() in ('', UPSTREAM_EMAIL_BUTTON_COLOR)
        ).write({'email_secondary_color': NODO_PRIMARY})

        bot = self.env.ref('base.partner_root', raise_if_not_found=False)
        if not bot:
            return
        bot = bot.sudo()
        if bot.name == UPSTREAM_BOT_NAME:
            bot.name = NODO_BOT_NAME
        upstream_image = _read_file(UPSTREAM_BOT_IMAGE)
        current = bot.image_1920
        current = getattr(current, 'content', current) if current else None
        if upstream_image and current and bytes(current) == upstream_image:
            nodo_image = _read_file(NODO_BOT_IMAGE)
            if nodo_image:
                bot.image_1920 = BinaryBytes(nodo_image, filename='nodo-icon-512.png')
