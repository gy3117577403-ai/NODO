from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # 单据上的讨论和 @ 提醒默认在系统内通知（讨论里的「单据」分栏），不发邮件：
    # NODO 内部协作以系统内消息为主，未配置外发邮件服务器时邮件通知也发不出去。
    notification_type = fields.Selection(default='inbox')

    def _store_init_fields(self, res):
        super()._store_init_fields(res)
        res.attr('nodo_can_manage_channels', lambda user: user._is_system())

    @api.model
    def _nodo_use_inbox_notifications(self):
        """首次安装时把已有内部用户的通知方式改为系统内通知。"""
        internal = self.sudo().with_context(active_test=False).search([('share', '=', False)])
        internal.filtered(lambda u: u.notification_type == 'email').write({'notification_type': 'inbox'})

    def _init_odoobot(self):
        """不启用上游机器人的新手引导对话（内容是上游产品的功能介绍）。"""
        self.ensure_one()
        self.sudo().odoobot_state = 'disabled'
        return self.env['discuss.channel']
