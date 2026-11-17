from datetime import timedelta

from markupsafe import Markup

from odoo import SUPERUSER_ID, Command, api, fields, models
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError, UserError


DISCUSS_INTERNAL_CHANGE = object()


class MailMessage(models.Model):
    _inherit = 'mail.message'

    nodo_removal = fields.Selection(
        [('recall', '撤回'), ('admin', '管理员删除')], readonly=True, copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Direct ORM creation, including default_* values, must obey the same posting rule as Discuss.
        missing = {field for vals in vals_list for field in ('model', 'res_id') if field not in vals}
        defaults = self.default_get(list(missing)) if missing else {}
        channel_ids = {
            int(res_id)
            for vals in vals_list
            if vals.get('model', defaults.get('model')) == 'discuss.channel'
            and (res_id := vals.get('res_id', defaults.get('res_id')))
        }
        if self.env.uid != SUPERUSER_ID and channel_ids and (
            'default_create_date' in self.env.context or any('create_date' in vals for vals in vals_list)
        ):
            raise AccessError('讨论消息的发送时间由系统记录。')
        if self.env.context.get('default_nodo_removal') or any(vals.get('nodo_removal') for vals in vals_list):
            raise AccessError('请通过讨论的撤回或管理员删除操作移除消息。')
        self.env['discuss.channel'].browse(channel_ids)._nodo_check_channel_post_access()
        messages = super().create(vals_list)
        messages._nodo_discuss_messages().attachment_ids._nodo_check_discuss_size()
        return messages

    def _nodo_discuss_messages(self):
        return self.sudo().filtered_domain([('model', '=', 'discuss.channel'), ('res_id', '!=', False)])

    def _nodo_check_message_access(self):
        self.ensure_one()
        if (
            not self.exists()
            or not self._nodo_discuss_messages()
            or not self.sudo(False).has_access('read')
        ):
            raise AccessError('你无权操作这条消息。')

    def _nodo_edit_deadline(self, seconds):
        self.ensure_one()
        if self.create_date and self.message_type == 'comment' and not self.nodo_removal:
            return self.create_date.replace(microsecond=0) + timedelta(seconds=seconds)
        return False

    def _nodo_within_edit_time(self):
        deadline = self._nodo_edit_deadline(self.env['discuss.channel']._nodo_recall_seconds())
        return deadline and fields.Datetime.now() < deadline

    def _nodo_check_edit(self):
        for message in self:
            message._nodo_check_message_access()
            if message.nodo_removal:
                raise AccessError('这条消息已撤回或删除。')
            if not message.is_current_user_or_guest_author or message.message_type != 'comment':
                raise AccessError('只能编辑自己发送的消息。')
            if not message._nodo_within_edit_time():
                raise AccessError('已超过消息编辑时限。')

    def write(self, vals):
        if self.env.context.get('_nodo_discuss_change') is DISCUSS_INTERNAL_CHANGE:
            return super().write(vals)
        if 'nodo_removal' in vals:
            raise AccessError('请通过讨论的撤回或管理员删除操作移除消息。')

        content_changed = {'body', 'subject', 'attachment_ids'} & vals.keys()
        identity_changed = {
            'date', 'create_date', 'model', 'res_id', 'message_type', 'author_id', 'author_guest_id',
        } & vals.keys()
        if not (content_changed or identity_changed):
            return super().write(vals)

        protected = self._nodo_discuss_messages()
        if protected and self.env.uid != SUPERUSER_ID:
            if identity_changed:
                raise AccessError('不能更改讨论消息的发送者、发送时间或所属会话。')
            if content_changed:
                protected._nodo_check_edit()
        result = super().write(vals)
        if 'attachment_ids' in vals:
            protected.attachment_ids._nodo_check_discuss_size()
        if content_changed and self.env.uid != SUPERUSER_ID and protected._filter_empty():
            raise UserError('如需移除整条消息，请使用撤回或管理员删除。')
        return result

    def unlink(self):
        if (
            self.env.uid != SUPERUSER_ID
            and self.env.context.get('_nodo_discuss_change') is not DISCUSS_INTERNAL_CHANGE
            and self._nodo_discuss_messages()
        ):
            raise AccessError('请通过讨论的撤回或管理员删除操作移除消息。')
        return super().unlink()

    def nodo_remove_discuss_message(self):
        self._nodo_remove_discuss_message()
        return Store().add(self.sudo(), '_store_message_fields')._build_result()

    def _nodo_remove_discuss_message(self):
        self._nodo_check_message_access()
        actor = self.env.user
        message = self.sudo()
        if message.nodo_removal:
            raise AccessError('这条消息已撤回或删除。')
        if message.is_current_user_or_guest_author and message._nodo_within_edit_time():
            removal = 'recall'
            author = message.author_id.name or message.author_guest_id.name or '成员'
            text = f'{author}撤回了一条消息'
        elif actor._is_system():
            removal = 'admin'
            text = '一条消息已被管理员删除'
        elif message.is_current_user_or_guest_author:
            raise AccessError('已超过消息撤回时限。')
        else:
            raise AccessError('只能撤回自己发送的消息。')

        message = message.with_context(_nodo_discuss_change=DISCUSS_INTERNAL_CHANGE)
        vals = {'nodo_removal': removal, 'pinned_at': False}
        if attachments := message.attachment_ids:
            shared = message.search([
                ('id', '!=', message.id), ('attachment_ids', 'in', attachments.ids),
            ]).attachment_ids
            owned = attachments.filtered(lambda attachment: (
                (attachment.res_model == message.model and attachment.res_id == message.res_id)
                or (attachment.res_model == 'mail.message' and attachment.res_id == message.id)
            ))
            # An independent attachment keeps its original access and other references.
            if detach := attachments - (owned - shared):
                vals['attachment_ids'] = [Command.unlink(attachment.id) for attachment in detach]
        message.write(vals)
        message.message_link_preview_ids._unlink_and_notify()
        channel = message.env['discuss.channel'].browse(message.res_id)
        channel._message_update_content(
            message, body=Markup('<p>%s</p>') % text, subject=False,
            partner_ids=[], attachment_ids=[], strict=False,
        )

    def _store_nodo_message_policy_fields(self, res: Store.FieldList):
        seconds = self.env['discuss.channel']._nodo_recall_seconds()
        in_discuss = lambda message: message.model == 'discuss.channel'
        res.attr('nodo_removal', predicate=in_discuss)
        res.attr('nodo_edit_deadline', lambda message: message._nodo_edit_deadline(seconds), predicate=in_discuss)

    def _store_message_fields(self, res: Store.FieldList, **kwargs):
        super()._store_message_fields(res, **kwargs)
        res.from_method('_store_nodo_message_policy_fields')
