from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('nodo', 'post_install', '-at_install')
class TestDepartmentDirectory(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hr = new_test_user(cls.env, login='department-hr@nodo.test', groups='hr.group_hr_user')
        department = cls.env['hr.department']
        cls.office, cls.workshop = department.create([{'name': '总经办'}, {'name': '研发工坊'}])
        cls.first_team, cls.second_team = department.create([
            {'name': '核对组', 'parent_id': cls.office.id},
            {'name': '核对组', 'parent_id': cls.workshop.id},
        ])
        cls.subteam = department.create({'name': '二次配线', 'parent_id': cls.first_team.id})
        cls.manager, cls.team_member, cls.subteam_member, cls.archived = cls.env['hr.employee'].create([
            {'name': '季岑', 'department_id': cls.office.id},
            {'name': '俞桐', 'department_id': cls.first_team.id},
            {'name': '祝宁', 'department_id': cls.subteam.id},
            {'name': '卢舟', 'department_id': cls.first_team.id, 'active': False},
        ])

    def test_same_name_path_search_and_branch_tree(self):
        directory = self.env['hr.department'].with_user(self.hr)
        action = self.env.ref('hr.hr_department_kanban_action')
        view = self.env.ref('nodo_staff_import.staff_department_directory_kanban')
        self.assertEqual(tuple(action.views[0]), (view.id, 'kanban'))
        kanban_arch = etree.fromstring(directory.get_view(view.id, 'kanban')['arch'])
        self.assertIsNotNone(kanban_arch.find("field[@name='nodo_has_subdepartments']"))
        search_arch = etree.fromstring(directory.get_view(action.search_view_id.id, 'search')['arch'])
        search_domain = search_arch.find("field[@name='name']").get('filter_domain')
        test_departments = self.first_team | self.second_team
        for term, expected in (('核对组', test_departments), ('研发工坊 / 核对组', self.second_team)):
            domain = safe_eval(search_domain, {'self': term})
            self.assertEqual(directory.search(domain + [('id', 'in', test_departments.ids)]), expected)

        branch = directory.search([('nodo_directory_branch_id', 'child_of', self.office.id)])
        self.assertEqual(branch, self.office | self.first_team | self.subteam)
        tree = directory.search_panel_select_range('nodo_directory_branch_id', expand=True, limit=0)
        self.assertEqual(tree['parent_field'], 'parent_id')
        values = {value['id']: value for value in tree['values']}
        for department in test_departments:
            value = values[department.id]
            self.assertEqual(value['parent_id'], department.parent_id.id)
            self.assertEqual(value['nodo_color'], department.nodo_directory_segments[-1]['color'])
        self.assertNotEqual(values[self.first_team.id]['nodo_color'], values[self.second_team.id]['nodo_color'])

    def test_counts_match_direct_and_subdepartment_employee_actions(self):
        department = self.office.with_user(self.hr)
        self.assertTrue(department.nodo_has_subdepartments)
        self.assertFalse(self.second_team.nodo_has_subdepartments)
        self.assertEqual(self.second_team.nodo_branch_staff_count, 0)
        for direct, expected in ((True, self.manager), (False, self.manager | self.team_member | self.subteam_member)):
            with self.subTest(direct=direct):
                action = department.with_context(nodo_department_direct=direct).action_nodo_view_department_staff()
                self.assertEqual(action['res_model'], 'hr.employee')
                self.assertEqual(self.env[action['res_model']].with_user(self.hr).search(action['domain']), expected)
                count = department.nodo_direct_staff_count if direct else department.nodo_branch_staff_count
                self.assertEqual(count, len(expected))

    def test_empty_department_uses_employee_list_without_sample_rows(self):
        empty_department = self.workshop.with_user(self.hr).with_context(nodo_department_direct=True)
        action = empty_department.action_nodo_view_department_staff()
        employees = self.env[action['res_model']].with_user(self.hr)
        self.assertEqual(employees.search_count(action['domain']), 0)
        view_id, view_type = action['views'][0]
        self.assertEqual(view_type, 'list')
        arch = etree.fromstring(employees.get_view(view_id, view_type)['arch'])
        self.assertEqual(arch.get('sample'), '0')

    def test_manager_without_hr_access_uses_public_employees_and_visible_departments(self):
        member = new_test_user(self.env, login='department-member@nodo.test', groups='base.group_user')
        self.manager.user_id = member
        self.office.manager_id = self.manager
        department = self.office.with_user(member)
        tree = department.search_panel_select_range('nodo_directory_branch_id')
        self.assertIn(self.first_team.id, [value['id'] for value in tree['values']])
        self.assertNotIn(self.second_team.id, [value['id'] for value in tree['values']])
        action = department.action_nodo_view_department_staff()
        self.assertEqual(action['res_model'], 'hr.employee.public')
        self.assertEqual(self.env[action['res_model']].with_user(member).search_count(action['domain']), 3)
        self.assertEqual(department.nodo_branch_staff_count, 3)
        with self.assertRaises(AccessError):
            self.second_team.with_user(member).action_nodo_view_department_staff()
