from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger
from odoo.tools.safe_eval import safe_eval


@tagged('nodo', 'post_install', '-at_install')
class TestMemberDirectory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee']
        cls.admin = new_test_user(
            cls.env, login='member-directory-admin@nodo.test', groups='base.group_system,hr.group_hr_user',
        )
        cls.officer = new_test_user(
            cls.env, login='member-directory-officer@nodo.test', groups='hr.group_hr_user',
        )
        cls.directory = cls.employee.with_user(cls.admin).with_company(cls.company)
        cls.department = cls.env['hr.department'].create({'name': '装配组', 'company_id': cls.company.id})
        cls.job = cls.env['hr.job'].create({
            'name': '装配协调', 'company_id': cls.company.id, 'department_id': cls.department.id,
        })
        cls.values = {'name': '顾桐', 'department': cls.department.id}

    def test_new_employee_enters_directory_without_an_account(self):
        users = self.env['res.users'].with_context(active_test=False)
        count = users.search_count([])
        result = self.directory.with_context(default_user_id=self.admin.id).nodo_add_member(self.values)
        member = self.employee.browse(result['id'])
        self.assertEqual(member.name, '顾桐')
        self.assertEqual(member.department_id, self.department)
        self.assertEqual(member.company_id, self.company)
        self.assertEqual(member.nodo_review_state, 'pending')
        self.assertEqual(member.nodo_account_state, 'none')
        self.assertFalse(member.nodo_personnel_number)
        self.assertFalse(member.job_id)
        self.assertFalse(member.user_id)
        self.assertEqual(users.search_count([]), count)
        view = self.env.ref('nodo_staff_import.staff_member_directory_list')
        self.assertEqual(tuple(self.env.ref('hr.open_view_employee_list_my').views[0]), (view.id, 'list'))

    def test_department_path_sort_spans_pages_and_follows_hierarchy_changes(self):
        departments = self.env['hr.department']
        east, west = departments.create([
            {'name': 'A 工程部', 'company_id': self.company.id},
            {'name': 'Z 工程部', 'company_id': self.company.id},
        ])
        east_group, west_group = departments.create([
            {'name': '配线组', 'parent_id': east.id, 'company_id': self.company.id},
            {'name': '配线组', 'parent_id': west.id, 'company_id': self.company.id},
        ])
        east_person, west_person = self.employee.create([
            {'name': '周谨', 'department_id': east_group.id},
            {'name': '安禾', 'department_id': west_group.id},
        ])
        directory = self.employee.with_user(self.officer)
        domain = [('id', 'in', (east_person | west_person).ids)]
        order = 'nodo_department_path, name, id'
        self.assertEqual(directory.search(domain, order=order, limit=1), east_person)
        self.assertEqual(directory.search(domain, order=order, limit=1, offset=1), west_person)
        self.assertEqual(directory.search(domain, order='nodo_department_path desc', limit=1), west_person)
        self.assertEqual([segment['id'] for segment in east_person.nodo_department_segments], [east.id, east_group.id])
        self.assertEqual(east_person.nodo_department_path, 'A 工程部 / 配线组')

        east.name = 'ZZ 工程部'
        self.assertEqual(directory.search(domain, order=order, limit=1), west_person)
        self.assertEqual(east_person.nodo_department_path, 'ZZ 工程部 / 配线组')
        east_group.parent_id = west_group
        self.assertEqual([segment['id'] for segment in east_person.nodo_department_segments], [west.id, west_group.id, east_group.id])
        self.assertEqual(east_person.nodo_department_path, 'Z 工程部 / 配线组 / 配线组')

    def test_department_colors_match_tree_and_path_with_and_without_filtering(self):
        departments = self.env['hr.department']
        office = departments.create({'name': '总经办', 'company_id': self.company.id})
        engineering, quality = departments.create([
            {'name': '工程部', 'parent_id': office.id, 'company_id': self.company.id},
            {'name': '质量部', 'parent_id': office.id, 'company_id': self.company.id},
        ])
        engineer, inspector = self.employee.with_user(self.officer).create([
            {'name': '程遥', 'department_id': engineering.id},
            {'name': '林沅', 'department_id': quality.id},
        ])
        office_segment, engineering_segment = engineer.nodo_department_segments
        _, quality_segment = inspector.nodo_department_segments
        self.assertEqual(office_segment, {'id': office.id, 'name': office.name, 'color': 0})
        self.assertNotEqual(engineering_segment['color'], quality_segment['color'])

        directory = self.employee.with_user(self.officer)
        for people in (engineer | inspector, engineer):
            values = directory.search_panel_select_range('department_id', search_domain=[('id', 'in', people.ids)])['values']
            tree = {value['id']: value['nodo_color'] for value in values}
            self.assertEqual(tree[office.id], office_segment['color'])
            self.assertEqual(tree[engineering.id], engineering_segment['color'])

    def test_ordinary_employee_directory_shares_department_colors_and_stays_read_only(self):
        member = new_test_user(self.env, login='public-directory-member@nodo.test', groups='base.group_user')
        office = self.env['hr.department'].create({'name': '总经办', 'company_id': self.company.id})
        assembly = self.env['hr.department'].create({
            'name': '配线组', 'parent_id': office.id, 'company_id': self.company.id,
        })
        employee = self.employee.with_user(self.officer).create({
            'name': '纪遥', 'department_id': assembly.id,
        })
        public_directory = self.env['hr.employee.public'].with_user(member)
        public_employee = public_directory.search([('id', '=', employee.id)])
        self.assertTrue(public_employee)
        self.assertEqual(public_employee.nodo_department_segments, employee.nodo_department_segments)
        self.assertFalse(public_employee.has_access('write'))
        self.assertNotIn('nodo_personnel_number', public_directory.fields_get())
        self.assertNotIn('nodo_account_state', public_directory.fields_get())

        values = public_directory.search_panel_select_range('department_id', search_domain=[
            ('id', '=', employee.id),
        ])['values']
        colors = {value['id']: value['nodo_color'] for value in values}
        for segment in public_employee.nodo_department_segments:
            self.assertEqual(colors[segment['id']], segment['color'])

    def test_public_directory_uses_its_kanban_and_searches_public_fields(self):
        member = new_test_user(self.env, login='public-directory-search@nodo.test', groups='base.group_user')
        employee = self.employee.create({
            'name': '闻理', 'job_title': '工序协调员', 'work_email': 'wells@nodo.test',
        })
        public_directory = self.env['hr.employee.public'].with_user(member)
        action = self.env.ref('hr.hr_employee_public_action')
        custom_view = self.env.ref('nodo_staff_import.staff_public_directory_kanban')
        self.assertEqual(tuple(action.views[0]), (custom_view.id, 'kanban'))
        self.assertEqual([view_type for _, view_type in action.views], ['kanban', 'list', 'hierarchy', 'form'])
        view = public_directory.get_view(view_id=action.search_view_id.id, view_type='search')
        search_arch = etree.fromstring(view['arch'])
        search_domain = search_arch.find("field[@name='name']").get('filter_domain')
        for keyword in ('闻理', '工序协调', 'wells@nodo.test'):
            with self.subTest(keyword=keyword):
                domain = safe_eval(search_domain, {'self': keyword})
                self.assertIn(employee.id, public_directory.search(domain).ids)

    def test_duplicate_number_blocks_save_and_same_name_can_be_confirmed(self):
        first = self.directory.nodo_add_member({**self.values, 'number': 'A_07'})
        with self.assertRaisesRegex(ValidationError, '人员编号已被使用') as raised:
            self.directory.nodo_add_member({**self.values, 'name': '魏楠', 'number': 'a_07'})
        self.assertEqual(raised.exception.context['employee_id'], first['id'])
        review = self.directory.nodo_add_member({**self.values, 'number': 'AX07'})
        self.assertEqual(review['matches'], [{'id': first['id'], 'department': '装配组', 'number': 'A_07'}])
        self.assertEqual(self.directory.search_count([('name', '=', '顾桐')]), 1)
        second = self.directory.nodo_add_member({**self.values, 'number': 'AX07'}, confirm_same_name=True)
        self.assertNotEqual(second['id'], first['id'])
        self.assertEqual(self.directory.search_count([('name', '=', '顾桐')]), 2)

    def test_department_and_job_are_checked_on_the_server(self):
        other_company = self.env['res.company'].create({'name': '栎桥工坊'})
        other_department = self.env['hr.department'].create({'name': '仓库', 'company_id': other_company.id})
        other_job = self.env['hr.job'].create({
            'name': '仓库收货', 'company_id': other_company.id, 'department_id': other_department.id,
        })
        options = self.directory.nodo_member_options()
        self.assertIn(self.department.id, [department['id'] for department in options['departments']])
        self.assertNotIn(other_department.id, [department['id'] for department in options['departments']])
        self.assertIn(self.job.id, [job['id'] for job in options['jobs']])
        with self.assertRaisesRegex(ValidationError, '当前公司可用的部门'):
            self.directory.nodo_add_member({**self.values, 'department': other_department.id})
        with self.assertRaisesRegex(ValidationError, '该部门的可用岗位'):
            self.directory.nodo_add_member({**self.values, 'job': other_job.id})
        result = self.directory.nodo_add_member({**self.values, 'job': self.job.id})
        self.assertEqual(self.employee.browse(result['id']).job_id, self.job)

    def test_hr_officer_cannot_use_admin_member_actions(self):
        officers = self.employee.with_user(self.officer)
        with self.assertRaises(AccessError):
            officers.nodo_member_options()
        with self.assertRaises(AccessError):
            officers.nodo_add_member(self.values)
        member = self.employee.browse(self.directory.nodo_add_member(self.values)['id'])
        with self.assertRaises(AccessError):
            member.with_user(self.officer).action_nodo_open_member_account()
        with self.assertRaises(AccessError):
            member.with_user(self.officer).nodo_create_member_account('member-officer@nodo.test')

    def test_hr_officer_can_fill_change_and_clear_job_without_affecting_account(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        self.assertFalse(member.job_id)
        self.assertFalse(member.nodo_personnel_number)
        member.nodo_create_member_account('member-job-edit@nodo.test')
        user = member.user_id
        role = self.env.ref('nodo_base.group_role_engineering')
        member.nodo_save_linked_roles(user.id, [], role.ids)
        account_fields = ['active', 'login', 'group_ids', 'all_group_ids', 'company_ids']
        original_account = user.read(account_fields)
        other_job = self.env['hr.job'].with_user(self.officer).create({
            'name': '工艺协调', 'company_id': self.company.id, 'department_id': self.department.id,
        })

        public_employee = self.env['hr.employee.public'].browse(member.id).with_user(user)
        for job in (self.job, other_job, self.env['hr.job']):
            with self.subTest(job=job.name):
                member.with_user(self.officer).write({'job_id': job.id})
                self.assertEqual(member.job_id, job)
                self.assertEqual(member.job_title, job.name)
                member.version_id.flush_recordset(['job_title'])
                public_employee.invalidate_recordset(['job_title'])
                self.assertEqual(public_employee.job_title, job.name)
                self.assertEqual(member.user_id, user)
                self.assertEqual(user.read(account_fields), original_account)
                self.assertEqual(member.nodo_review_state, 'pending')
                self.assertFalse(member.nodo_personnel_number)

        with self.assertRaises(AccessError):
            member.with_user(user).write({'job_id': self.job.id})
        self.assertFalse(member.job_id)

    def test_hr_job_change_checks_department_company_and_job_status(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        wrong_department = self.env['hr.department'].create({'name': '料件组', 'company_id': self.company.id})
        outside_company = self.env['res.company'].create({'name': '岫岭工坊'})
        wrong_department_job, archived_job, outside_job = self.env['hr.job'].create([
            {'name': '领料员', 'department_id': wrong_department.id},
            {'name': '班组协调', 'department_id': self.department.id, 'active': False},
            {'name': '装配协调', 'company_id': outside_company.id},
        ])
        officer = member.with_user(self.officer)
        for job in (wrong_department_job, archived_job, outside_job):
            with self.subTest(job=job.id), self.assertRaises((AccessError, ValidationError)), self.env.cr.savepoint():
                officer.write({'job_id': job.id})
        self.assertFalse(member.job_id)
        outside_employee = self.employee.with_company(outside_company).create({'name': '梁漪'})
        with self.assertRaises(AccessError):
            outside_employee.with_context(allowed_company_ids=self.company.ids).with_user(self.officer).write({'job_id': False})

    def test_unassigned_custom_title_survives_unrelated_employee_save(self):
        member = self.employee.create({'name': '陈玥', 'job_title': '装配联络'})
        member.with_user(self.officer).write({'job_id': False, 'work_phone': '12345'})
        self.assertFalse(member.job_id)
        self.assertEqual(member.job_title, '装配联络')

    def test_employee_detail_opens_the_separate_account_form(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        action = member.action_nodo_open_member_account()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'nodo_staff_open_account')
        self.assertEqual(action['params']['id'], member.id)
        self.assertEqual(action['params']['name'], member.name)
        self.assertNotIn('login', action['params'])
        self.assertFalse(member.user_id)

    def test_account_creation_links_an_internal_user_without_sending_an_invitation(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        work_contact = self.env['res.partner'].create({'name': member.name, 'email': 'member-contact@nodo.test'})
        member.work_contact_id = work_contact
        result = member.with_context(
            no_reset_password=False, default_group_ids=[Command.link(self.env.ref('base.group_system').id)],
        ).nodo_create_member_account('  member-activation@nodo.test  ')
        user = self.env['res.users'].browse(result['id'])
        self.assertEqual(member.user_id.id, user.id)
        self.assertEqual(user.login, 'member-activation@nodo.test')
        self.assertEqual(user.partner_id, work_contact)
        self.assertEqual(user.company_id, self.company)
        self.assertEqual(user.company_ids, self.company)
        internal_group = self.env.ref('base.group_user')
        allowed_groups = internal_group | self.env.ref('mail.group_mail_notification_type_inbox')
        self.assertIn(internal_group, user.group_ids)
        self.assertFalse(user.group_ids - allowed_groups)
        if 'signup_type' in work_contact._fields:
            self.assertFalse(work_contact.signup_type)
        self.assertEqual(member.nodo_account_state, 'active')
        with self.assertRaisesRegex(ValidationError, '已关联账号'):
            member.action_nodo_open_member_account()
        with self.assertRaisesRegex(ValidationError, '已关联账号'):
            member.nodo_create_member_account('member-retry@nodo.test')

    @mute_logger('odoo.sql_db')
    def test_invalid_login_leaves_the_employee_unlinked(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        for login, message in [('  ', '请填写登录名'), (self.admin.login, '此登录名已被使用')]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValidationError, message) as error:
                    member.nodo_create_member_account(login)
                self.assertEqual(error.exception.context['supplement_field'], 'login')
                self.assertFalse(member.user_id)
                self.assertEqual(member.nodo_account_state, 'none')

    def test_linked_account_entry_requires_the_correct_employee_and_user(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        member.nodo_create_member_account('linked-account@nodo.test')
        user = member.user_id.with_user(self.admin)
        action = user.with_context(nodo_linked_employee_id=member.id).get_record_default_action()
        self.assertEqual(action['res_model'], 'hr.employee')
        self.assertEqual(action['path'], 'employee-account')
        self.assertEqual(action['res_id'], member.id)
        self.assertEqual(user.get_record_default_action()['res_model'], 'res.users')
        self.assertEqual(member.action_nodo_open_linked_user_settings(user.id)['res_model'], 'res.users')
        self.assertEqual(member.nodo_linked_account_info()['userId'], user.id)
        with self.assertRaisesRegex(ValidationError, '关联用户已变化'):
            self.admin.with_user(self.admin).with_context(nodo_linked_employee_id=member.id).get_record_default_action()
        with self.assertRaisesRegex(ValidationError, '关联用户已变化'):
            member.action_nodo_linked_password(self.admin.id)
        officer = member.with_user(self.officer)
        with self.assertRaises(AccessError):
            officer.nodo_linked_account_info()
        with self.assertRaises(AccessError):
            officer.nodo_save_linked_roles(user.id, [], [])
        with self.assertRaises(AccessError):
            officer.action_nodo_linked_password(user.id)

    def test_linked_role_changes_preserve_other_groups_and_reject_stale_edits(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        member.nodo_create_member_account('linked-roles@nodo.test')
        user = member.user_id
        extra = self.env.ref('base.group_allow_export')
        user.write({'group_ids': [Command.link(extra.id)]})
        sales = self.env.ref('nodo_base.group_role_sales')
        engineering = self.env.ref('nodo_base.group_role_engineering')
        roles = member.nodo_save_linked_roles(user.id, [], [sales.id, engineering.id])
        self.assertEqual({group_id for row in roles for group_id in row['direct']}, {sales.id, engineering.id})
        self.assertIn(extra, user.group_ids)
        with self.assertRaisesRegex(ValidationError, '已被更新'):
            member.nodo_save_linked_roles(user.id, [], [])
        with self.assertRaisesRegex(ValidationError, '请选择 NODO 业务角色'):
            member.nodo_save_linked_roles(user.id, [sales.id, engineering.id], [self.env.ref('base.group_system').id])
        member.nodo_save_linked_roles(user.id, [sales.id, engineering.id], [engineering.id])
        self.assertEqual(user.group_ids & (sales | engineering | extra), engineering | extra)

    def test_linked_role_groups_show_inheritance_and_limit_each_privilege(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        member.nodo_create_member_account('linked-inherited-role@nodo.test')
        purchase = self.env.ref('nodo_base.group_role_purchase')
        privilege = self.env['res.groups.privilege'].create({
            'name': '采购岗位', 'category_id': self.env.ref('nodo_base.module_category_nodo_roles').id,
        })
        choices = self.env['res.groups'].create([
            {'name': '采购助理', 'privilege_id': privilege.id, 'implied_ids': [Command.link(purchase.id)]},
            {'name': '采购经理', 'privilege_id': privilege.id, 'implied_ids': [Command.link(purchase.id)]},
        ])
        with self.assertRaisesRegex(ValidationError, '只能选择一项'):
            member.nodo_save_linked_roles(member.user_id.id, [], choices.ids)
        roles = member.nodo_save_linked_roles(member.user_id.id, [], choices[:1].ids)
        inherited = next(item for item in roles if item['id'] == purchase.privilege_id.id)
        self.assertEqual(inherited['direct'], [])
        self.assertEqual(inherited['inherited'], [purchase.name])

    def test_detail_starts_with_the_profile_and_respects_hr_permissions(self):
        view = self.env.ref('nodo_staff_import.staff_employee_detail_form')
        action = self.env.ref('hr.open_view_employee_list_my')
        self.assertIn((view.id, 'form'), [tuple(item) for item in action.views])
        for user in (self.admin, self.officer):
            with self.subTest(user=user.login):
                arch = etree.fromstring(self.employee.with_user(user).get_view(view_id=view.id)['arch'])
                overview = arch.find('.//notebook/page')
                self.assertEqual(overview.get('name'), 'nodo_employee_profile')
                self.assertIsNotNone(overview.find('.//field[@name="work_email"]'))
                self.assertIsNone(overview.find('.//field[@name="wage"]'))
                self.assertIsNotNone(arch.find('.//span[@invisible="active"]'))
                self.assertIsNone(arch.find('.//button[@name="action_send_invitation"]'))
                avatar = arch.find('.//field[@name="image_1920"]')
                self.assertEqual(avatar.get('widget'), 'nodo_staff_avatar')
                job_field = arch.find('.//page[@name="work_information"]//field[@name="job_id"]')
                self.assertEqual(job_field.get('widget'), 'nodo_staff_job')
                self.assertEqual(
                    arch.find('.//page[@name="hr_settings"]//button[@name="action_nodo_open_member_account"]') is not None,
                    user == self.admin,
                )
                self.assertEqual(
                    arch.find('.//widget[@name="nodo_employee_supplement"]') is not None,
                    user == self.admin,
                )
                statuses = arch.find('.//div[@class="o_nodo_profile_statuses"]')
                for status in ('nodo_review_state', 'nodo_account_state'):
                    self.assertEqual(statuses.find(f'field[@name="{status}"]') is not None, user == self.admin)

    def test_employee_invitation_actions_are_disabled(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        with self.assertRaisesRegex(UserError, '开通或管理账号'):
            member.action_send_invitation()
        with self.assertRaisesRegex(UserError, '开通或管理账号'):
            member.action_copy_invitation_link()
        self.assertFalse(member.user_id)
        self.assertEqual(member.nodo_account_state, 'none')
