import json

from odoo import Command
from odoo.addons.mail.tools.discuss import Store
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools.convert import convert_file


SALES_ROLES = ('sales', 'costing', 'approval')
PRODUCTION_ROLES = ('engineering', 'purchase', 'production', 'operator', 'quality')


@tagged('nodo', 'post_install', '-at_install')
class TestNodoChannels(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        cls.Channel = cls.env['discuss.channel']
        cls.general = cls.env.ref('mail.channel_all_employees')
        cls.quotes = cls.env.ref('nodo_base.channel_sales_quotes')
        cls.production = cls.env.ref('nodo_base.channel_production_coordination')
        cls.admin_channel = cls.env.ref('mail.channel_admin')
        cls.admin = cls.env.ref('base.user_admin')
        cls.employees = {
            key: new_test_user(env, login=f'channel_{key}@nodo.test', groups=f'nodo_base.group_role_{key}')
            for key in SALES_ROLES + PRODUCTION_ROLES
        }
        cls.employee = new_test_user(env, login='channel_employee@nodo.test')
        cls.sales = cls.employees['sales']
        cls.approval = cls.employees['approval']

    def test_default_channels_and_automatic_members(self):
        channels = self.Channel.search([('channel_type', '=', 'channel'), ('parent_channel_id', '=', False)])
        self.assertEqual(channels, self.general | self.quotes | self.production | self.admin_channel)
        self.assertEqual((self.general | self.quotes | self.production).mapped('name'), ['全员通知', '销售报价', '生产协调'])
        self.assertEqual(self.general.group_ids, self.env.ref('base.group_user'))
        self.assertEqual(self.admin_channel.group_public_id, self.env.ref('base.group_system'))
        self.assertTrue(self.admin_channel.with_user(self.admin).has_access('read'))
        self.assertFalse(self.admin_channel.with_user(self.sales).has_access('read'))
        self.assertIn(self.employee.partner_id, self.general.channel_partner_ids)
        self.assertNotIn(self.employee.partner_id, self.quotes.channel_partner_ids | self.production.channel_partner_ids)
        for role, user in self.employees.items():
            with self.subTest(role=role):
                self.assertIn(user.partner_id, self.general.channel_partner_ids)
                expected, other = (self.quotes, self.production) if role in SALES_ROLES else (self.production, self.quotes)
                self.assertIn(user.partner_id, expected.channel_partner_ids)
                self.assertNotIn(user.partner_id, other.channel_partner_ids)

    def test_install_welcome_kept_out_of_announcement(self):
        welcome = self.env.ref('mail.module_install_notification')
        self.assertTrue(welcome.exists())
        self.assertTrue(welcome.body)
        self.assertNotIn(welcome, self.general.message_ids)
        self.assertNotIn(welcome, self.general._get_last_messages())

    def test_upgrade_preserves_admin_changes_and_does_not_recreate_deleted_default(self):
        self.quotes.with_user(self.admin).name = '订单报价协调'
        self.general.with_user(self.admin).nodo_restrict_posting = False
        self.production.with_user(self.admin).unlink()
        convert_file(self.env, 'nodo_base', 'data/discuss_channels.xml', idref={}, mode='update')
        self.assertEqual(self.quotes.name, '订单报价协调')
        self.assertFalse(self.general.nodo_restrict_posting)
        self.assertFalse(self.env.ref('nodo_base.channel_production_coordination', raise_if_not_found=False))

    def test_production_role_assignment_adds_member_and_native_removal_retains_member(self):
        role = self.env.ref('nodo_base.group_role_production')
        self.assertNotIn(self.employee.partner_id, self.production.channel_partner_ids)
        self.employee.write({'group_ids': [Command.link(role.id)]})
        self.assertIn(self.employee.partner_id, self.production.channel_partner_ids)
        self.employee.write({'group_ids': [Command.unlink(role.id)]})
        self.assertFalse(self.employee.has_group('nodo_base.group_role_production'))
        self.assertIn(self.employee.partner_id, self.production.channel_partner_ids)

    def test_announcement_rejects_post_and_direct_message_create(self):
        channel = self.general.with_user(self.sales)
        for actor_channel in (channel, channel.sudo()):
            with self.assertRaisesRegex(AccessError, '可发言权限组'):
                actor_channel.message_post(body='销售发言', message_type='comment')
        messages = self.env['mail.message'].with_user(self.sales)
        with self.assertRaisesRegex(AccessError, '可发言权限组'):
            messages.create({'body': '直接发言', 'model': 'discuss.channel', 'res_id': channel.id})
        with self.assertRaisesRegex(AccessError, '可发言权限组'):
            messages.with_context(default_model='discuss.channel', default_res_id=channel.id).create({'body': '直接发言'})
        with self.assertRaisesRegex(AccessError, '只有系统管理员'):
            channel.write({'nodo_restrict_posting': False})

    def test_announcement_policy_applies_to_channel_threads(self):
        with self.assertRaisesRegex(AccessError, '可发言权限组'):
            self.general.with_user(self.sales)._create_sub_channel(name='公告讨论')
        thread = self.general.with_user(self.approval)._create_sub_channel(name='公告讨论')
        with self.assertRaisesRegex(AccessError, '可发言权限组'):
            thread.with_user(self.sales).message_post(body='讨论串发言', message_type='comment')

    def test_announcement_permissions_follow_store_viewer(self):
        self.assertTrue(self.general.nodo_restrict_posting)
        self.assertEqual(
            self.general.nodo_posting_group_ids,
            self.env.ref('base.group_system') | self.env.ref('nodo_base.group_role_approval'),
        )
        for user, allowed in ((self.sales, False), (self.approval, True), (self.admin, True)):
            with self.subTest(user=user.id):
                store = Store().add(self.general.with_user(user), '_store_channel_fields')._build_result()
                data = next(c for c in store['discuss.channel'] if c['id'] == self.general.id)
                self.assertTrue(data['nodo_restrict_posting'])
                self.assertEqual(data['nodo_can_post'], allowed)
                self.assertNotIn('nodo_posting_group_ids', data)

    def test_channel_create_and_delete_are_admin_only_and_chat_still_works(self):
        employee_channels = self.Channel.with_user(self.sales)
        for model in (employee_channels, employee_channels.with_context(default_channel_type='channel').sudo()):
            with self.assertRaisesRegex(AccessError, '只有系统管理员可以新建频道'):
                model.create({'name': '协作频道'})
        channel = self.Channel.with_user(self.admin).create({'name': '协作频道'})
        with self.assertRaises(AccessError):
            channel.with_user(self.sales).unlink()
        with self.assertRaisesRegex(AccessError, '只有系统管理员可以删除频道'):
            channel.with_user(self.sales).sudo().unlink()
        channel.unlink()
        self.assertFalse(channel.exists())
        self.assertEqual(employee_channels._get_or_create_chat(self.approval.partner_id.ids).channel_type, 'chat')
        self.assertEqual(employee_channels._create_group(self.sales | self.approval | self.employee).channel_type, 'group')


@tagged('nodo', 'post_install', '-at_install')
class TestNodoAnnouncementHttp(HttpCase):

    def _request(self, route, params):
        response = self.url_open(
            f'{route}?db={self.env.cr.dbname}',
            data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'call', 'params': params}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_announcement_post_route_and_reaction(self):
        context = {'no_reset_password': True}
        sales = new_test_user(self.env, login='announcement_sales@nodo.test', groups='nodo_base.group_role_sales', context=context)
        approval = new_test_user(self.env, login='announcement_approval@nodo.test', groups='nodo_base.group_role_approval', context=context)
        channel = self.env.ref('mail.channel_all_employees')
        params = {
            'thread_model': 'discuss.channel', 'thread_id': channel.id,
            'post_data': {'body': '公告内容', 'message_type': 'comment', 'subtype_xmlid': 'mail.mt_comment'},
        }

        self.authenticate(sales.login, sales.login)
        refused = self._request('/mail/message/post', params)
        self.assertIn('可发言权限组', refused['error']['data']['message'])
        self.authenticate(approval.login, approval.login)
        posted = self._request('/mail/message/post', params)
        message_id = posted['result']['message_id']
        self.assertTrue(message_id)
        admin_message = channel.with_user(self.env.ref('base.user_admin')).message_post(
            body='管理员公告', message_type='comment',
        )
        self.assertTrue(admin_message.id)
        self.authenticate(sales.login, sales.login)
        reacted = self._request('/mail/message/reaction', {'message_id': message_id, 'content': '👍', 'action': 'add'})
        self.assertIn('result', reacted)
        self.assertTrue(self.env['mail.message.reaction'].sudo().search_count([
            ('message_id', '=', message_id), ('partner_id', '=', sales.partner_id.id), ('content', '=', '👍'),
        ]))
