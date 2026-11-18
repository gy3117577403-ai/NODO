from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestEmployeePlan(TransactionCase):
    def test_default_employee_plans_keep_order_assignment_and_deadline(self):
        expected = {
            'hr.onboarding_plan': ('入职计划', (
                ('准备办公电脑及相关设备', 10, 'on_demand'),
                ('安排入职培训', 20, 'on_demand'),
                ('参加入职培训', 30, 'employee'),
            )),
            'hr.offboarding_plan': ('离职计划', (
                ('安排团队工作交接', 10, 'manager'),
                ('收回人事发放的物品', 20, 'manager'),
            )),
        }
        for xmlid, (name, steps) in expected.items():
            plan = self.env.ref(xmlid)
            self.assertEqual(plan.name, name)
            self.assertEqual(plan.res_model, 'hr.employee')
            self.assertEqual(
                [(s.summary, s.sequence, s.responsible_type) for s in plan.template_ids],
                list(steps),
            )
            self.assertTrue(all(
                (s.delay_count, s.delay_unit, s.delay_from) == (0, 'days', 'before_plan_date')
                for s in plan.template_ids
            ))

    def test_default_localization_keeps_custom_text_and_scheduling_rules(self):
        plan = self.env.ref('hr.onboarding_plan')
        plan.name = '工艺培训计划'
        self.env.ref('hr.onboarding_setup_it_materials').summary = '准备工段工具'
        step = self.env.ref('hr.onboarding_plan_training')
        step.write({
            'summary': 'Plan Training',
            'sequence': 25,
            'responsible_type': 'manager',
            'delay_count': 2,
            'delay_unit': 'weeks',
            'delay_from': 'after_plan_date',
        })

        self.env['mail.activity.plan']._nodo_localize_employee_plan_defaults()
        self.env['mail.activity.plan']._nodo_localize_employee_plan_defaults()

        self.assertEqual(plan.name, '工艺培训计划')
        self.assertEqual(self.env.ref('hr.onboarding_setup_it_materials').summary, '准备工段工具')
        self.assertEqual(step.summary, '安排入职培训')
        self.assertEqual(
            (step.sequence, step.responsible_type, step.delay_count, step.delay_unit, step.delay_from),
            (25, 'manager', 2, 'weeks', 'after_plan_date'),
        )

    def test_employee_plan_action_opens_configured_views(self):
        action = self.env.ref('hr.mail_activity_plan_action')
        self.assertEqual(
            [tuple(view) for view in action.views],
            [
                (self.env.ref('nodo_staff_import.employee_plan_list').id, 'list'),
                (self.env.ref('nodo_staff_import.employee_plan_kanban').id, 'kanban'),
                (self.env.ref('nodo_staff_import.employee_plan_form').id, 'form'),
            ],
        )
        form = etree.fromstring(self.env['mail.activity.plan'].get_view(action.views[-1][0], 'form')['arch'])
        steps = form.find(".//field[@name='template_ids']")
        self.assertIn('nodo_staff_import.employee_plan_step_form', steps.get('context'))
        self.assertEqual(steps.find('list/control/create').get('string'), '添加步骤')
        self.assertEqual(steps.find("list/field[@name='delay_count']").get('widget'), 'nodo_employee_plan_deadline')
