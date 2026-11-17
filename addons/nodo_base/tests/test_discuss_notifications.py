from datetime import datetime
from unittest.mock import patch

from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestDiscussNotifications(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        cls.sender = new_test_user(env, login='notice_sender@nodo.test', name='周工')
        cls.reader = new_test_user(env, login='notice_reader@nodo.test', name='林工')
        cls.channel = cls.env['discuss.channel']._create_group(cls.sender | cls.reader)
        cls.member = cls.channel.channel_member_ids.filtered(
            lambda member: member.partner_id == cls.reader.partner_id
        )

    def _post(self, **kwargs):
        return self.channel.with_user(self.sender).message_post(
            body='更新了装配清单', message_type='comment', subtype_xmlid='mail.mt_comment', **kwargs,
        )

    def _init_store(self):
        user = self.reader.with_user(self.reader)
        return Store().add(user, '_store_init_fields')._build_result()

    def test_own_preferences_are_writable_and_loaded_in_store(self):
        reader = self.reader.with_user(self.reader)
        self.assertTrue(reader.nodo_desktop_notifications)
        self.assertTrue(reader.nodo_message_sound)
        reader.write({'nodo_desktop_notifications': False, 'nodo_message_sound': False})
        reader.res_users_settings_id.set_res_users_settings({'nodo_notification_hint_dismissed': True})

        settings = self._init_store()['res.users.settings'][0]
        self.assertFalse(settings['nodo_desktop_notifications'])
        self.assertFalse(settings['nodo_message_sound'])
        self.assertTrue(settings['nodo_notification_hint_dismissed'])
        self.assertTrue(self.sender.nodo_message_sound)
        with self.assertRaises(AccessError):
            self.sender.with_user(reader).write({'nodo_message_sound': False})

    def test_muted_member_receives_unread_counts_but_no_push_even_for_a_mention(self):
        self.member.with_user(self.reader).mute_until_dt = datetime.max
        self.assertFalse(self.member.message_unread_counter)
        with patch.object(type(self.channel), '_web_push_send_notification') as send, patch.object(
            type(self.channel), '_web_push_get_partners_parameters',
            side_effect=lambda partner_ids: (partner_ids, None, None),
        ):
            self._post(partner_ids=self.reader.partner_id.ids)
            self._post()
            send.assert_not_called()
            self.member.with_user(self.reader).mute_until_dt = False
            self._post()
            send.assert_called_once()

        # The initial Store is built in a separate request, without the unread
        # value cached above before the messages were posted.
        self.member.invalidate_recordset(['message_unread_counter'])
        self.assertEqual(self.member.message_unread_counter, 3)
        user = self._init_store()['res.users'][0]
        counts = {item['id']: item for item in user['nodo_unread_channels']}
        self.assertEqual(counts[self.channel.id], {'id': self.channel.id, 'tab': 'chat', 'count': 3})

    def test_push_respects_desktop_and_sound_preferences_and_links_to_channel(self):
        reader = self.reader.with_user(self.reader)
        with patch.object(type(self.channel), '_web_push_send_notification') as send, patch.object(
            type(self.channel), '_web_push_get_partners_parameters',
            side_effect=lambda partner_ids: (partner_ids, None, None),
        ):
            reader.nodo_desktop_notifications = False
            self._post()
            send.assert_not_called()
            reader.write({'nodo_desktop_notifications': True, 'nodo_message_sound': False})
            message = self._post()
            send.assert_called_once()
            devices = send.call_args.args[0]
            self.assertEqual(devices, {self.reader.partner_id.id})
            payload = send.call_args.kwargs['payload']
            self.assertEqual(payload['title'], '周工')
            self.assertEqual(payload['options']['body'], '更新了装配清单')
            self.assertEqual(payload['options']['icon'], '/nodo_base/static/img/nodo-icon-192.png')
            self.assertTrue(payload['options']['silent'])
            self.assertEqual(payload['options']['data'], {
                'action': 'mail.action_discuss',
                'message_id': message.id,
                'model': 'discuss.channel',
                'res_id': self.channel.id,
            })
