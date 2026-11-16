from odoo import api, fields, models

NODO_PRIMARY = '#1F4F46'
UPSTREAM_EMAIL_BUTTON_COLOR = '#875A7B'
UPSTREAM_BOT_NAME = 'OdooBot'
NODO_BOT_NAME = 'NODO 助手'


class ResCompany(models.Model):
    _inherit = 'res.company'

    # 邮件按钮和门户页面（含登录页）按钮、链接都用这个颜色，默认改为 NODO 主色。
    email_secondary_color = fields.Char(default=NODO_PRIMARY)

    @api.model
    def _nodo_apply_branding(self):
        """安装或升级时执行，只改仍是上游默认值的数据，用户自己改过的不动。

        - 公司邮件按钮色：上游默认紫色改为 NODO 主色；
        - 系统机器人联系人：上游名称改为「NODO 助手」。
        """
        companies = self.sudo().with_context(active_test=False).search([])
        companies.filtered(
            lambda c: (c.email_secondary_color or '').upper() in ('', UPSTREAM_EMAIL_BUTTON_COLOR)
        ).write({'email_secondary_color': NODO_PRIMARY})

        bot = self.env.ref('base.partner_root', raise_if_not_found=False)
        if bot and bot.sudo().name == UPSTREAM_BOT_NAME:
            bot.sudo().name = NODO_BOT_NAME
