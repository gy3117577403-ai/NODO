from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # 单据上的讨论和 @ 提醒默认在系统内通知（讨论里的「单据」分栏），不发邮件：
    # NODO 内部协作以系统内消息为主，未配置外发邮件服务器时邮件通知也发不出去。
    notification_type = fields.Selection(
        selection_add=[('inbox', '系统内通知')],
        default='inbox',
        help='选择「系统内通知」后，可在讨论的「单据」中查看相关讨论和提醒。',
    )
    nodo_desktop_notifications = fields.Boolean(
        related='res_users_settings_id.nodo_desktop_notifications',
        readonly=False, user_writeable=True, groups='base.group_user',
    )
    nodo_message_sound = fields.Boolean(
        related='res_users_settings_id.nodo_message_sound',
        readonly=False, user_writeable=True, groups='base.group_user',
    )

    def _store_init_fields(self, res):
        super()._store_init_fields(res)
        res.attr('nodo_can_manage_channels', lambda user: user._is_system())
        if self._is_internal():
            res.attr('nodo_unread_channels', self._nodo_unread_channels())

    def _nodo_unread_channels(self):
        self.ensure_one()
        # Keep this snapshot as small as the native tab counters. The Store uses
        # live member counters as soon as the corresponding channel is loaded.
        members = self.env['discuss.channel.member'].sudo().search_fetch([
            ('partner_id', '=', self.partner_id.id),
            ('is_pinned', '=', True),
            ('channel_id.active', '=', True),
        ], ['channel_id', 'message_unread_counter'])
        readable_channels = self.env['discuss.channel'].search_fetch([
            ('id', 'in', members.channel_id.ids),
        ], ['channel_type', 'default_display_mode', 'parent_channel_id'])
        tabs = {
            channel.id: 'channel' if channel.channel_type == 'channel' else 'chat'
            for channel in readable_channels
            if 'video_full_screen' not in (
                channel.default_display_mode, channel.parent_channel_id.default_display_mode,
            )
        }
        return [
            {
                'id': member.channel_id.id,
                'tab': tabs[member.channel_id.id],
                'count': member.message_unread_counter,
            }
            for member in members
            if member.channel_id.id in tabs and member.message_unread_counter
        ]

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
