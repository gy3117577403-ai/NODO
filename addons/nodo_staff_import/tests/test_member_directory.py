from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


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

    def test_employee_detail_opens_the_separate_account_form(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        action = member.action_nodo_open_member_account()
        self.assertEqual(action['res_model'], 'res.users')
        self.assertEqual(action['context']['default_create_employee_id'], member.id)
        self.assertTrue(action['context']['no_reset_password'])
        self.assertNotIn('default_login', action['context'])
        user = self.env['res.users'].with_context(action['context']).create({
            'name': member.name, 'login': 'member-activation@nodo.test', 'create_employee_id': member.id,
        })
        self.assertEqual(member.user_id.id, user.id)
        self.assertEqual(member.nodo_account_state, 'active')
        with self.assertRaisesRegex(ValidationError, '已关联账号'):
            member.action_nodo_open_member_account()

    def test_employee_invitation_actions_are_disabled(self):
        member = self.directory.browse(self.directory.nodo_add_member(self.values)['id'])
        with self.assertRaisesRegex(UserError, '开通或管理账号'):
            member.action_send_invitation()
        with self.assertRaisesRegex(UserError, '开通或管理账号'):
            member.action_copy_invitation_link()
        self.assertFalse(member.user_id)
        self.assertEqual(member.nodo_account_state, 'none')
