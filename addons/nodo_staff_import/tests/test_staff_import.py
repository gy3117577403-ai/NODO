import csv
import io

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import BinaryBytes

from ..models.staff_import import REQUIRED_HEADERS


HEADERS = (*REQUIRED_HEADERS, '已有登录名')


@tagged('nodo', 'post_install', '-at_install')
class TestStaffImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.employee = cls.env['hr.employee']
        cls.wizard = cls.env['nodo.staff.import']
        cls.admin_user = new_test_user(
            cls.env, login='staff-admin@nodo.test', groups='base.group_system',
        )
        cls.internal_user = new_test_user(
            cls.env, login='staff-employee@nodo.test', groups='nodo_base.group_role_engineering',
        )

    def _create_wizard(self, rows, company=None, user=None):
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(HEADERS)
        writer.writerows(rows)
        model = self.wizard.with_user(user) if user else self.wizard
        return model.create({
            'company_id': (company or self.company).id,
            'roster_file': BinaryBytes(stream.getvalue().encode('utf-8-sig')),
            'roster_filename': '人员确认.csv',
        })

    def _employee(self, number, company=None):
        return self.employee.with_context(active_test=False).search([
            ('company_id', '=', (company or self.company).id), ('nodo_personnel_number', '=', number),
        ])

    def test_supplement_uses_employee_fields_and_preserves_review(self):
        department = self.env['hr.department'].create({'name': '装配组'})
        tag = self.employee._nodo_pending_review_tag()
        job = self.env['hr.job'].create({'name': '装配员', 'department_id': department.id})
        person = self.employee.create({
            'name': '周岚', 'department_id': department.id, 'category_ids': [Command.link(tag.id)],
            'additional_note': '架构图来源编号 ORG-0032\n其他备注',
        })
        profile = person.nodo_supplement
        self.assertEqual(profile['sourceNumber'], 'ORG-0032')
        self.assertEqual(profile['review'], 'pending')
        person.write({'nodo_supplement': {
            'changes': {'number': '0007', 'job': '装配员'}, 'original': {'number': '', 'job': '', 'department': department.id},
        }})
        self.assertEqual(person.nodo_personnel_number, '0007')
        self.assertEqual(person.job_id, job)
        self.assertEqual(person.category_ids, tag)
        self.assertEqual(person.nodo_supplement['review'], 'pending')
        self.assertEqual(person.nodo_supplement['sourceNumber'], 'ORG-0032')

    def test_supplement_partial_save_and_job_in_selected_department(self):
        department = self.env['hr.department'].create({'name': '计划组'})
        person = self.employee.create({'name': '程蘅'})
        self.assertEqual(person.nodo_supplement['review'], 'unknown')
        person.write({'nodo_supplement': {
            'changes': {'department': department.id}, 'original': {'department': False},
        }})
        self.assertFalse(person.job_id)
        self.assertFalse(person.nodo_personnel_number)
        with self.assertRaisesRegex(ValidationError, '部门已变更'), self.env.cr.savepoint():
            person.write({'nodo_supplement': {
                'changes': {'job': '排产协调'}, 'original': {'job': '', 'department': False},
            }})
        person.write({'nodo_supplement': {
            'changes': {'job': '排产协调'}, 'original': {'job': '', 'department': department.id},
        }})
        self.assertEqual(person.job_id.department_id, department)
        self.assertEqual(person.job_id.company_id, person.company_id)
        self.assertEqual(person.nodo_supplement['job'], '排产协调')
        self.assertEqual(person.nodo_supplement['review'], 'unknown')

    def test_supplement_rejects_duplicate_stale_and_out_of_company_values(self):
        department = self.env['hr.department'].create({'name': '协作组'})
        self.employee.create({'name': '林筱', 'nodo_personnel_number': 'A_01', 'department_id': department.id})
        person = self.employee.create({'name': '周岚', 'department_id': department.id})
        with self.assertRaisesRegex(ValidationError, '编号已被使用'), self.env.cr.savepoint():
            person.write({'nodo_supplement': {
                'changes': {'number': 'a_01', 'name': '临时改名'}, 'original': {'number': '', 'name': '周岚'},
            }})
        self.assertEqual(person.name, '周岚')
        person.write({'nodo_supplement': {'changes': {'number': 'A%01'}, 'original': {'number': ''}}})
        with self.assertRaisesRegex(ValidationError, '已被修改'), self.env.cr.savepoint():
            person.write({'nodo_supplement': {'changes': {'number': '0008'}, 'original': {'number': ''}}})
        outside = self.env['res.company'].create({'name': '山岚工坊'})
        branch = self.env['hr.department'].create({'name': '车间', 'company_id': outside.id})
        with self.assertRaisesRegex(ValidationError, '可用的部门'), self.env.cr.savepoint():
            person.write({'nodo_supplement': {
                'changes': {'department': branch.id}, 'original': {'department': department.id},
            }})
        self.assertEqual(person.department_id, department)
        self.assertEqual(person.nodo_personnel_number, 'A%01')

    def test_supplement_respects_existing_employee_access(self):
        person = self.employee.create({'name': '周岚'}).with_user(self.internal_user)
        with self.assertRaises(AccessError):
            person.read(['nodo_supplement'])
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            person.write({'nodo_supplement': {'changes': {'name': '任宁'}, 'original': {'name': '周岚'}}})
        self.assertEqual(person.sudo().name, '周岚')

    def test_preview_and_import_department_hierarchy(self):
        rows = [
            ('021', '许禾', '运营部 / 备料组', '物料协调', '通过', ''),
            ('022', '唐川', '运营部 / 备料组', '物料协调', '通过', ''),
            ('023', '江栩', '运营部 / 备料组', '物料协调', '待复核', ''),
        ]
        wizard = self._create_wizard(rows, user=self.admin_user)
        wizard.action_preview()
        self.assertIn('新增 2', wizard.summary)
        self.assertIn('跳过 1', wizard.summary)
        self.assertFalse(self._employee('021'))
        self.assertFalse(self.env['hr.department'].search([('name', '=', '备料组')]))
        wizard.action_import()
        first = self._employee('021')
        second = self._employee('022')
        self.assertEqual(first.department_id.complete_name, '运营部 / 备料组')
        self.assertEqual(first.department_id, second.department_id)
        self.assertEqual(first.job_id, second.job_id)
        self.assertEqual(first.job_id.department_id, first.department_id)
        self.assertFalse(self._employee('023'))
        self.assertFalse(first.user_id)
        self.assertFalse(wizard.roster_file)
        batch = self.env['nodo.staff.import.batch'].search([('company_id', '=', self.company.id)], limit=1)
        self.assertEqual((batch.created_count, batch.skipped_count), (2, 1))
        self.assertEqual(batch.create_uid, self.admin_user)

    def test_repeated_file_and_update_match_official_number(self):
        rows = [('031', '袁临', '协作组', '采购助理', '通过', '')]
        original = self._create_wizard(rows)
        original.action_preview()
        original.action_import()
        employee = self._employee('031')
        repeat = self._create_wizard(rows)
        repeat.action_preview()
        self.assertIn('新增 0', repeat.summary)
        self.assertIn('更新 0', repeat.summary)
        self.assertIn('档案一致', repeat.details)
        with self.assertRaisesRegex(UserError, '没有可导入'):
            repeat.action_import()
        revision = self._create_wizard([('031', '袁临', '协调部 / 采购组', '采购', '通过', '')])
        revision.action_preview()
        self.assertIn('更新 1', revision.summary)
        self.assertIn('协调部 / 采购组 · 采购', revision.details)
        revision.action_import()
        self.assertEqual(self._employee('031'), employee)
        self.assertEqual(employee.department_id.complete_name, '协调部 / 采购组')
        self.assertEqual(employee.job_id.name, '采购')

    def test_links_existing_internal_login_without_mutating_permissions(self):
        roles = self.internal_user.group_ids
        users = self.env['res.users'].with_context(active_test=False).search_count([])
        wizard = self._create_wizard([
            ('041', '白沐', '工艺组', '规格核对', '通过', self.internal_user.login),
        ])
        wizard.action_preview()
        wizard.action_import()
        person = self._employee('041')
        self.assertEqual(person.user_id, self.internal_user)
        self.assertEqual(person.user_id.group_ids, roles)
        self.assertEqual(self.env['res.users'].with_context(active_test=False).search_count([]), users)
        conflict = self._create_wizard([
            ('042', '林溦', '工艺组', '规格核对', '通过', self.internal_user.login),
        ])
        conflict.action_preview()
        self.assertIn('已用于其他人员', conflict.details)

    def test_conflicts_excluded_and_distinct_numbers_allow_same_name(self):
        self.employee.create({'name': '顾青', 'company_id': self.company.id})
        wizard = self._create_wizard([
            ('051', '顾青', '工艺组', '规格核对', '通过', ''),
            ('052', '曲云', '工艺组', '规格核对', '通过', ''),
            ('052', '宁木', '工艺组', '规格核对', '通过', ''),
            ('', '何苇', '工艺组', '规格核对', '通过', ''),
            ('054', '梅远', '工艺组', '规格核对', '通过', ''),
            ('055', '梅远', '工艺组', '规格核对', '通过', ''),
        ])
        wizard.action_preview()
        self.assertIn('冲突 4', wizard.summary)
        self.assertIn('已有同名未编号档案', wizard.details)
        self.assertIn('表内人员编号重复', wizard.details)
        wizard.action_import()
        self.assertFalse(self._employee('051'))
        self.assertFalse(self._employee('052'))
        self.assertNotEqual(self._employee('054'), self._employee('055'))

    def test_company_scope_allows_distinct_companies_to_use_same_number(self):
        other_company = self.env['res.company'].create({'name': '杉谷工坊'})
        rows = [('061', '梁霁', '协调组', '采购助理', '通过', '')]
        for company in (self.company, other_company):
            wizard = self._create_wizard(rows, company=company)
            wizard.action_preview()
            wizard.action_import()
        self.assertNotEqual(self._employee('061'), self._employee('061', other_company))
        other = self._create_wizard(rows, company=other_company).with_user(self.admin_user)
        with self.assertRaises(AccessError):
            other.action_preview()

    def test_requires_system_administrator_even_in_elevated_context(self):
        wizard = self._create_wizard([('071', '施岚', '协调组', '采购', '通过', '')])
        with self.assertRaises(AccessError):
            self.wizard.with_user(self.internal_user).create({'company_id': self.company.id})
        with self.assertRaisesRegex(AccessError, '系统管理员'):
            wizard.with_user(self.internal_user).sudo().action_preview()
        with self.assertRaisesRegex(AccessError, '系统管理员'):
            wizard.with_user(self.internal_user).sudo().action_import()

    def test_stale_preview_is_rejected_before_writing(self):
        rows = [('081', '姜葵', '制造协作部', '采购', '通过', '')]
        wizard = self._create_wizard(rows)
        wizard.action_preview()
        rival = self._create_wizard([('082', '何清', '制造协作部', '采购', '通过', '')])
        rival.action_preview()
        rival.action_import()
        with self.assertRaisesRegex(UserError, '请重新预检'):
            wizard.action_import()
        self.assertFalse(self._employee('081'))
        wizard.action_preview()
        wizard.action_import()
        self.assertEqual(self._employee('081').department_id, self._employee('082').department_id)
        self.assertEqual(self._employee('081').job_id, self._employee('082').job_id)

    def test_first_excel_sheet_is_read_and_keeps_text_number(self):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '人员确认'
        sheet.append(HEADERS)
        sheet.append(('0009', '程简', '协调部 / 采购组', '采购', '通过', ''))
        workbook.create_sheet('填写说明').append(['导入步骤'])
        stream = io.BytesIO()
        workbook.save(stream)
        wizard = self.wizard.create({
            'roster_file': BinaryBytes(stream.getvalue()), 'roster_filename': '员工确认.xlsx',
        })
        wizard.action_preview()
        self.assertIn('0009', wizard.details)
        wizard.action_import()
        self.assertEqual(self._employee('0009').name, '程简')

    def test_inactive_login_and_other_company_login_conflict(self):
        inactive_user = new_test_user(self.env, login='staff-old@nodo.test', groups='base.group_user')
        inactive_user.active = False
        outside_company = self.env['res.company'].create({'name': '雾岚工坊'})
        different_company_user = new_test_user(
            self.env, login='staff-outside@nodo.test', groups='base.group_user',
            company_id=outside_company.id, company_ids=[Command.set(outside_company.ids)],
        )
        wizard = self._create_wizard([
            ('091', '安蒲', '技术组', '工艺员', '通过', inactive_user.login),
            ('092', '常松', '技术组', '工艺员', '通过', different_company_user.login),
        ])
        wizard.action_preview()
        self.assertIn('冲突 2', wizard.summary)
        self.assertFalse(wizard.has_changes)
