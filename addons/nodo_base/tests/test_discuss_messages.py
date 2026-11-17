from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussMessages(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        cls.author = new_test_user(env, login='discuss_author@nodo.test', name='周工')
        cls.reader = new_test_user(env, login='discuss_reader@nodo.test', name='林工')
        cls.admin = cls.env.ref('base.user_admin')
        cls.channel = cls.env['discuss.channel']._create_group(cls.author | cls.reader | cls.admin)
        cls.parameters = cls.env['ir.config_parameter'].sudo()

    def _post(self, **kwargs):
        return self.channel.with_user(self.author).message_post(
            body='柜体装配顺序', message_type='comment', subtype_xmlid='mail.mt_comment', **kwargs,
        )

    def _after_window(self, message):
        self.parameters.set_int('nodo.discuss.recall_seconds', 3)
        return self.mock_datetime_and_now(message.create_date + timedelta(seconds=10))

    def test_author_can_recall_within_window_and_attachment_is_removed(self):
        self.assertEqual(self.channel._nodo_recall_seconds(), 120)
        message = self._post(attachments=[('装配清单.txt', b'Assembly check list')])
        attachment = message.attachment_ids
        self.assertTrue(attachment)
        result = message.with_user(self.author).nodo_remove_discuss_message()
        self.assertTrue(message.exists())
        self.assertEqual(message.nodo_removal, 'recall')
        self.assertIn('周工撤回了一条消息', message.body)
        self.assertNotIn('柜体装配顺序', message.body)
        self.assertFalse(message.attachment_ids)
        self.assertFalse(attachment.exists())
        self.assertEqual(result['mail.message'][0]['nodo_removal'], 'recall')

    def test_recall_beyond_configured_window_is_refused_on_both_entry_points(self):
        message = self._post()
        as_author = message.with_user(self.author)
        with self._after_window(message):
            with self.assertRaisesRegex(AccessError, '已超过消息撤回时限'):
                as_author.nodo_remove_discuss_message()
            with self.assertRaisesRegex(AccessError, '已超过消息撤回时限'):
                self.channel.with_user(self.author)._message_update_content(
                    as_author.sudo(), body='', attachment_ids=[],
                )
        with self.assertRaisesRegex(AccessError, '发送时间'):
            as_author.sudo().write({'create_date': fields.Datetime.now()})
        self.assertFalse(message.nodo_removal)
        self.assertIn('柜体装配顺序', message.body)

    def test_member_cannot_recall_another_members_message(self):
        message = self._post().with_user(self.reader)
        self.assertTrue(message.has_access('read'))
        with self.assertRaisesRegex(AccessError, '只能撤回自己发送的消息'):
            message.nodo_remove_discuss_message()
        with self.assertRaisesRegex(AccessError, '只能撤回自己发送的消息'):
            message.sudo().nodo_remove_discuss_message()
        self.assertFalse(message.nodo_removal)

    def test_admin_can_remove_another_members_expired_message(self):
        message = self._post()
        as_admin = message.with_user(self.admin)
        with self.assertRaisesRegex(AccessError, '请通过讨论'):
            as_admin.unlink()
        with self._after_window(message):
            as_admin.nodo_remove_discuss_message()
        self.assertTrue(message.exists())
        self.assertEqual(message.nodo_removal, 'admin')
        self.assertIn('一条消息已被管理员删除', message.body)

    def test_native_edit_marks_message_and_expired_edits_are_refused(self):
        message = self._post()
        as_author = message.with_user(self.author).sudo()
        channel = self.channel.with_user(self.author)
        channel._message_update_content(as_author, body='复核后的装配顺序')
        self.assertIn('复核后的装配顺序', message.body)
        self.assertIn('o-mail-Message-edited', message.body)
        with self._after_window(message):
            with self.assertRaisesRegex(AccessError, '已超过消息编辑时限'):
                channel._message_update_content(as_author, body='再次编辑')
            with self.assertRaisesRegex(AccessError, '已超过消息编辑时限'):
                as_author.write({'body': '直接编辑'})
        self.assertIn('复核后的装配顺序', message.body)

    def test_plain_native_delete_also_leaves_the_recall_placeholder(self):
        message = self._post().with_user(self.author).sudo()
        self.channel.with_user(self.author)._message_update_content(message, body='', attachment_ids=[])
        self.assertEqual(message.nodo_removal, 'recall')
        self.assertIn('周工撤回了一条消息', message.body)

    def test_discuss_attachment_size_is_enforced_when_posting(self):
        self.assertEqual(self.channel._nodo_file_limit_mb(), 50)
        self.parameters.set_int('nodo.discuss.file_limit_mb', 1)
        with self.assertRaisesRegex(ValidationError, '单个文件不能超过 1 MB'), self.env.cr.savepoint():
            self._post(attachments=[('装配索引.bin', b'0' * (1024**2 + 1))])
        message = self._post(attachments=[('装配索引.txt', b'Valid attachment')])
        self.assertEqual(message.attachment_ids.file_size, len(b'Valid attachment'))


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussMessageUpload(HttpCase):

    def test_pending_upload_rejects_file_over_configured_limit(self):
        author = new_test_user(
            self.env, login='discuss_upload@nodo.test', context={'no_reset_password': True},
        )
        channel = self.env['discuss.channel']._create_group(author | self.env.ref('base.user_admin'))
        self.env['ir.config_parameter'].sudo().set_int('nodo.discuss.file_limit_mb', 1)
        self.authenticate(author.login, author.login)
        route = f'/mail/attachment/upload?db={self.env.cr.dbname}'
        fields = {
            'csrf_token': self.csrf_token(), 'thread_model': 'discuss.channel',
            'thread_id': channel.id, 'is_pending': 'true',
        }
        oversized = self.url_open(
            route, data=fields,
            files={'ufile': ('柜体索引.bin', b'0' * (1024**2 + 1), 'application/octet-stream')},
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()['error']['message'], '单个文件不能超过 1 MB。')
        accepted = self.url_open(
            route, data=fields, files={'ufile': ('柜体清单.txt', b'Assembly list', 'text/plain')},
        )
        self.assertEqual(accepted.status_code, 200)
        attachment_id = accepted.json()['data']['attachment_id']
        self.assertEqual(self.env['ir.attachment'].browse(attachment_id).res_model, 'mail.compose.message')
