from odoo import SUPERUSER_ID, api, fields, models
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.tools import is_html_empty

from .mail_message import DISCUSS_INTERNAL_CHANGE
from .res_partner import nodo_text_avatar_svg


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    nodo_restrict_posting = fields.Boolean('仅指定人员可发言')
    nodo_posting_group_ids = fields.Many2many(
        'res.groups', 'nodo_discuss_channel_post_group_rel', 'channel_id', 'group_id',
        string='可发言权限组', groups='base.group_system',
        help='成员属于任一指定权限组即可发言。权限也适用于该频道下的讨论串。',
    )
    _nodo_posting_channel_type = models.Constraint(
        "CHECK (nodo_restrict_posting IS NOT TRUE OR (channel_type = 'channel' AND parent_channel_id IS NULL))",
        '只有频道可以设置指定人员发言。',
    )

    @api.model_create_multi
    def create(self, vals_list):
        missing = {
            field for vals in vals_list for field in ('channel_type', 'parent_channel_id') if field not in vals
        }
        defaults = self.default_get(list(missing)) if missing else {}
        if not self.env.user._is_system() and any(
            vals.get('channel_type', defaults.get('channel_type', 'channel')) == 'channel'
            and not vals.get('parent_channel_id', defaults.get('parent_channel_id'))
            for vals in vals_list
        ):
            raise AccessError('只有系统管理员可以新建频道。')
        parent_ids = {
            int(parent_id) for vals in vals_list
            if (parent_id := vals.get('parent_channel_id', defaults.get('parent_channel_id')))
        }
        self.browse(parent_ids)._nodo_check_channel_post_access()
        return super().create(vals_list)

    @api.ondelete(at_uninstall=False)
    def _nodo_check_channel_delete_access(self):
        if not self.env.user._is_system() and any(
            channel.channel_type == 'channel' and not channel.parent_channel_id for channel in self.sudo()
        ):
            raise AccessError('只有系统管理员可以删除频道。')

    def write(self, vals):
        posting_policy_changed = bool({'nodo_restrict_posting', 'nodo_posting_group_ids'} & vals.keys())
        if posting_policy_changed and not self.env.user._is_system():
            raise AccessError('只有系统管理员可以修改频道发言权限。')
        result = super().write(vals)
        if posting_policy_changed and not self.env.context.get('install_mode'):
            for channel in self.filtered(lambda item: item.channel_type == 'channel' and not item.parent_channel_id):
                # Invalidate each viewer's cached answer without sharing the allowed groups.
                Store(bus_channel=channel).add(channel, {
                    'nodo_restrict_posting': channel.nodo_restrict_posting,
                    'nodo_can_post': None,
                })
        return result

    def unlink(self):
        # mail.thread.unlinks its messages as part of deleting the parent channel.
        return super(DiscussChannel, self.with_context(_nodo_discuss_change=DISCUSS_INTERNAL_CHANGE)).unlink()

    def _notify_thread_by_web_push(self, message, recipients_data, **kwargs):
        recipients = [recipient for recipient in recipients_data if recipient['notif'] == 'web_push']
        if not recipients:
            return
        partner_ids = [recipient['id'] for recipient in recipients]
        # Native push routing includes mentions even when a channel is muted.
        # Filter only the push delivery so unread and inbox updates still run.
        muted = set(self.env['discuss.channel.member'].sudo().search_fetch([
            ('channel_id', '=', self.id),
            ('partner_id', 'in', partner_ids),
            ('mute_until_dt', '>', fields.Datetime.now()),
        ], ['partner_id']).partner_id.ids)
        settings = self.env['res.users.settings'].sudo().search([
            ('user_id.partner_id', 'in', partner_ids),
            ('user_id.active', '=', True),
            ('user_id.share', '=', False),
        ])
        settings_by_partner = {item.user_id.partner_id.id: item for item in settings}
        by_silence = {False: [], True: []}
        for recipient in recipients:
            partner_id = recipient['id']
            preferences = settings_by_partner.get(partner_id)
            if partner_id not in muted and (not preferences or preferences.nodo_desktop_notifications):
                by_silence[bool(preferences and not preferences.nodo_message_sound)].append(recipient)
        for silent, targets in by_silence.items():
            if targets:
                channel = self.with_context(nodo_push_silent=silent)
                super(DiscussChannel, channel)._notify_thread_by_web_push(message, targets, **kwargs)

    def _notify_by_web_push_prepare_payload(self, message, force_record_name=False):
        payload = super()._notify_by_web_push_prepare_payload(message, force_record_name=force_record_name)
        author = message.author_id or message.author_guest_id
        payload['title'] = (self.name if self.channel_type == 'channel' else author.name) or '新消息'
        options = payload['options']
        options['body'] = ' '.join(options['body'].split())[:180] or '你收到了一条新消息。'
        options['icon'] = '/nodo_base/static/img/nodo-icon-192.png'
        options['silent'] = bool(self.env.context.get('nodo_push_silent'))
        return payload

    @api.model
    def _nodo_recall_seconds(self):
        return max(0, self.env['ir.config_parameter'].sudo().get_int('nodo.discuss.recall_seconds', 120))

    @api.model
    def _nodo_file_limit_mb(self):
        value = self.env['ir.config_parameter'].sudo().get_int('nodo.discuss.file_limit_mb', 50)
        return value if value > 0 else 50

    def _nodo_channels_disallowing_posts(self, user):
        if not self or user.id == SUPERUSER_ID:
            return self.browse()
        # sudo reads the policy only. The posting check uses the original user, also on mail routes using sudo.
        channels = self.sudo().exists()
        restricted = (channels | channels.parent_channel_id).filtered('nodo_restrict_posting')
        if not restricted:
            return restricted
        groups = user.sudo().all_group_ids
        return restricted.filtered(lambda channel: not (channel.nodo_posting_group_ids & groups))

    def _nodo_check_channel_post_access(self):
        if self._nodo_channels_disallowing_posts(self.env.user):
            raise AccessError('你不在本频道的可发言权限组中，无法发言。')

    def message_post(self, *, message_type='notification', partner_ids=None, **kwargs):
        self._nodo_check_channel_post_access()
        return super().message_post(message_type=message_type, partner_ids=partner_ids, **kwargs)

    def _message_update_content(self, message, /, *, body, attachment_ids=None, **kwargs):
        if self.env.context.get('_nodo_discuss_change') is not DISCUSS_INTERNAL_CHANGE:
            if body is not None and is_html_empty(body) and (
                attachment_ids == [] or (attachment_ids is None and not message.sudo().attachment_ids)
            ):
                return message._nodo_remove_discuss_message()
            message._nodo_check_edit()
        return super()._message_update_content(message, body=body, attachment_ids=attachment_ids, **kwargs)

    def _store_message_update_extra_fields(self, res: Store.FieldList):
        super()._store_message_update_extra_fields(res)
        res.from_method('_store_nodo_message_policy_fields')

    def _store_channel_fields(self, res):
        super()._store_channel_fields(res)
        res.attr('nodo_file_limit_mb', lambda channel: channel._nodo_file_limit_mb())
        res.attr('nodo_restrict_posting', predicate=lambda channel: channel.channel_type == 'channel')
        if viewer := res.target_user():
            res.attr(
                'nodo_can_post', lambda channel: not channel._nodo_channels_disallowing_posts(viewer),
                predicate=lambda channel: channel.channel_type == 'channel',
            )

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        return (*super()._get_view_cache_key(view_id, view_type, **options), self.env.user._is_system())

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type in ('kanban', 'list', 'form') and not self.env.user._is_system():
            arch.set('create', '0')
        return arch, view

    def _generate_avatar(self):
        """频道和群聊的默认头像改用 NODO 色板加首字（上游是随机颜色）。上传了图片的不受影响。"""
        if self.channel_type == 'channel' or (
            self.channel_type == 'group' and self.default_display_mode != 'video_full_screen'
        ):
            return nodo_text_avatar_svg(self.display_name, f'{self.channel_type}-{self.id}')
        return super()._generate_avatar()
