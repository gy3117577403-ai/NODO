from odoo import fields, models


class ResUsersSettings(models.Model):
    _inherit = 'res.users.settings'

    nodo_desktop_notifications = fields.Boolean('新消息桌面通知', default=True)
    nodo_message_sound = fields.Boolean('新消息提示音', default=True)
    nodo_notification_hint_dismissed = fields.Boolean('已关闭开启通知提示')

    def _store_settings_fields(self, res):
        super()._store_settings_fields(res)
        res.extend([
            'nodo_desktop_notifications', 'nodo_message_sound', 'nodo_notification_hint_dismissed',
        ])
