from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('nodo', 'post_install', '-at_install')
class TestStaffDiscuss(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env['res.users'].with_context(no_reset_password=True).env
        company = env.company
        cls.viewer = new_test_user(env, login='staff_chat_viewer@nodo.test')
        cls.buyer = new_test_user(
            env, login='staff_chat_buyer@nodo.test', name='赵时安', groups='nodo_base.group_role_purchase',
        )
        cls.engineer = new_test_user(
            env, login='staff_chat_engineer@nodo.test', name='赵时安', groups='nodo_base.group_role_engineering',
        )
        cls.other_company = env['res.company'].create({'name': '桐青协作社'})
        cls.other_company_user = new_test_user(
            env, login='staff_chat_outside_company@nodo.test', name='赵时安',
            company_id=cls.other_company.id, company_ids=[Command.set(cls.other_company.ids)],
        )
        cls.disabled = new_test_user(env, login='staff_chat_disabled@nodo.test', name='停用同事')
        cls.portal = new_test_user(
            env, login='staff_chat_portal@nodo.test', name='外部同事', groups='base.group_portal', notification_type='email',
        )
        cls.disabled.active = False

        department = env['hr.department']
        cls.root = department.create({'name': '生产事务组', 'company_id': company.id})
        cls.purchase = department.create({'name': '采购联络组', 'company_id': company.id, 'parent_id': cls.root.id})
        cls.engineering = department.create({'name': '技术联络组', 'company_id': company.id, 'parent_id': cls.root.id})
        env['hr.employee'].create([
            {'name': user.name, 'user_id': user.id, 'company_id': company.id, 'department_id': dept.id}
            for user, dept in [(cls.buyer, cls.purchase), (cls.engineer, cls.engineering)]
        ])
        env['hr.employee'].create({'name': '朱望', 'department_id': cls.purchase.id, 'company_id': company.id})

        cls.access_group = env['res.groups'].create({'name': '生产协作访问组'})
        (cls.viewer | cls.buyer).write({'group_ids': [Command.link(cls.access_group.id)]})
        cls.channel = env['discuss.channel'].with_user(env.ref('base.user_admin')).create({
            'name': '生产协作', 'channel_type': 'channel', 'group_public_id': cls.access_group.id,
        })
        cls.directory = env['res.partner'].with_user(cls.viewer)

    def test_search_combines_name_department_and_role(self):
        search = self.directory.nodo_search_chat_people
        self.assertCountEqual(search(search_term='赵时安')['partner_ids'], (self.buyer | self.engineer).partner_id.ids)
        by_role = search(search_term='赵时安', department_id=self.root.id, role='purchase')
        self.assertEqual(by_role['partner_ids'], self.buyer.partner_id.ids)
        self.assertEqual(search(search_term='采购联络组')['partner_ids'], self.buyer.partner_id.ids)
        self.assertEqual(search(search_term='采购')['partner_ids'], self.buyer.partner_id.ids)
        self.assertEqual(search(search_term='赵', department_id=self.engineering.id)['partner_ids'], self.engineer.partner_id.ids)
        self.assertFalse(search(search_term='赵', department_id=self.engineering.id, role='purchase')['partner_ids'])
        fields = by_role['store_data']._build_result()['res.partner'][0]
        self.assertEqual(fields['nodo_chat_department'], '生产事务组 / 采购联络组')
        self.assertNotIn('email', fields)
        self.assertNotIn('phone', fields)

    def test_search_excludes_unavailable_people(self):
        search = self.directory.nodo_search_chat_people
        for name in ['停用同事', '外部同事', '朱望']:
            self.assertFalse(search(search_term=name)['partner_ids'])
        with self.assertRaises(AccessError):
            self.directory.with_user(self.portal).nodo_search_chat_people()

    def test_channel_search_preserves_read_scope_and_existing_members(self):
        search = self.directory.nodo_search_chat_people
        self.assertEqual(search(channel_id=self.channel.id, search_term='赵')['partner_ids'], self.buyer.partner_id.ids)
        self.channel._add_members(users=self.buyer, post_joined_message=False)
        self.assertFalse(search(channel_id=self.channel.id, search_term='赵')['partner_ids'])
        with self.assertRaises(AccessError):
            self.directory.with_user(self.engineer).nodo_search_chat_people(channel_id=self.channel.id)

    def test_add_is_immediate_and_does_not_duplicate_or_send_email(self):
        channel = self.channel.with_user(self.viewer)
        mail_domain = [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id)]
        mail = self.env['mail.mail']
        before = mail.search_count(mail_domain)
        result = channel.nodo_add_staff_members(self.buyer.partner_id.ids)
        self.assertEqual(result['added_count'], 1)
        member = channel.channel_member_ids.filtered(lambda entry: entry.partner_id == self.buyer.partner_id)
        self.assertEqual(len(member), 1)
        self.assertFalse(member.invitation_sent_dt)
        self.assertEqual(channel.nodo_add_staff_members(self.buyer.partner_id.ids)['added_count'], 0)
        self.assertEqual(mail.search_count(mail_domain), before)

    def test_add_rejects_ineligible_selections_as_a_unit(self):
        channel = self.channel.with_user(self.viewer)
        for ineligible in self.engineer | self.other_company_user | self.disabled | self.portal:
            with self.assertRaises(AccessError):
                channel.nodo_add_staff_members((self.buyer | ineligible).partner_id.ids)
        self.assertNotIn(self.buyer.partner_id, channel.channel_partner_ids)
        with self.assertRaises(AccessError):
            self.channel.with_user(self.engineer).nodo_add_staff_members(self.buyer.partner_id.ids)

    def test_admin_channel_keeps_its_original_access_group(self):
        admin_channel = self.env.ref('mail.channel_admin')
        self.assertEqual(admin_channel.group_public_id, self.env.ref('base.group_system'))
        with self.assertRaises(AccessError):
            self.directory.nodo_search_chat_people(channel_id=admin_channel.id)
        with self.assertRaises(AccessError):
            admin_channel.with_user(self.viewer).nodo_add_staff_members(self.buyer.partner_id.ids)
        result = admin_channel.with_user(self.env.ref('base.user_admin'))
        with self.assertRaises(AccessError):
            result.nodo_add_staff_members(self.buyer.partner_id.ids)
