from odoo.tests import TransactionCase, new_test_user, tagged

ROLE_XMLIDS = [
    'nodo_base.group_role_sales',
    'nodo_base.group_role_costing',
    'nodo_base.group_role_approval',
    'nodo_base.group_role_engineering',
    'nodo_base.group_role_purchase',
    'nodo_base.group_role_production',
    'nodo_base.group_role_operator',
    'nodo_base.group_role_quality',
]


@tagged('nodo', 'post_install', '-at_install')
class TestNodoRoles(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env.ref('nodo_base.module_category_nodo_roles')
        cls.roles = [cls.env.ref(x) for x in ROLE_XMLIDS]

    def test_eight_roles_in_nodo_category(self):
        names = [g.privilege_id.name for g in self.roles]
        self.assertEqual(names, ['销售', '核算', '批准', '技术', '采购', '生产', '车间操作', '质检'])
        # 按权限范围的顺序排列，用户表单上的显示顺序与此一致
        self.assertEqual(self.roles, sorted(self.roles, key=lambda g: g.privilege_id.sequence))
        for group in self.roles:
            self.assertEqual(group.privilege_id.category_id, self.category)
            # 每个权限范围只有一个组，用户表单上各角色独立选择
            self.assertEqual(len(group.privilege_id.group_ids), 1)

    def test_roles_only_imply_internal_user(self):
        # 上游会给隐含「内部用户」的组自动补上「普通用户」（区别于 Light 用户）；除此之外不应隐含任何应用权限。
        group_user = self.env.ref('base.group_user')
        allowed = group_user | self.env.ref('base.group_user_regular')
        for group in self.roles:
            self.assertIn(group_user, group.implied_ids, group.name)
            self.assertLessEqual(group.implied_ids, allowed, group.name)

    def test_user_gets_only_assigned_role(self):
        user = new_test_user(self.env, login='role_sales_only@nodo.test', groups='nodo_base.group_role_sales')
        self.assertTrue(user.has_group('nodo_base.group_role_sales'))
        self.assertTrue(user.has_group('base.group_user'))
        self.assertFalse(user.share)
        for xmlid in ROLE_XMLIDS[1:]:
            self.assertFalse(user.has_group(xmlid), xmlid)
        self.assertFalse(user.has_group('base.group_system'))

    def test_user_can_hold_several_roles(self):
        user = new_test_user(
            self.env, login='role_multi@nodo.test',
            groups='nodo_base.group_role_sales,nodo_base.group_role_costing',
        )
        self.assertTrue(user.has_group('nodo_base.group_role_sales'))
        self.assertTrue(user.has_group('nodo_base.group_role_costing'))
        self.assertFalse(user.has_group('nodo_base.group_role_approval'))

    def test_apps_menu_only_for_administrators(self):
        menu = self.env.ref('base.menu_management')
        self.assertEqual(menu.group_ids, self.env.ref('base.group_system'))
        user = new_test_user(self.env, login='role_menu@nodo.test', groups='nodo_base.group_role_sales')
        self.assertNotIn(menu.id, self.env['ir.ui.menu'].with_user(user)._visible_menu_ids())
        self.assertIn(menu.id, self.env['ir.ui.menu']._visible_menu_ids())
