from odoo import api, models


_DEFAULT_EMPLOYEE_PLANS = (
    (
        'hr.onboarding_plan', 'Onboarding', '入职计划',
        (
            ('hr.onboarding_setup_it_materials', 'Setup IT Materials', '准备办公电脑及相关设备'),
            ('hr.onboarding_plan_training', 'Plan Training', '安排入职培训'),
            ('hr.onboarding_training', 'Training', '参加入职培训'),
        ),
    ),
    (
        'hr.offboarding_plan', 'Offboarding', '离职计划',
        (
            ('hr.offboarding_setup_compute_out_delais', 'Organize knowledge transfer inside the team', '安排团队工作交接'),
            ('hr.offboarding_take_back_hr_materials', 'Take Back HR Materials', '收回人事发放的物品'),
        ),
    ),
)


class EmployeePlan(models.Model):
    _inherit = 'mail.activity.plan'

    @api.model
    def _nodo_localize_employee_plan_defaults(self):
        # The source defaults are stored record values. Keep user-edited names and summaries.
        for xmlid, source_name, localized_name, steps in _DEFAULT_EMPLOYEE_PLANS:
            plan = self.env.ref(xmlid, raise_if_not_found=False)
            if not plan or plan.res_model != 'hr.employee':
                continue
            if plan.name == source_name:
                plan.name = localized_name
            for step_xmlid, source_summary, localized_summary in steps:
                step = self.env.ref(step_xmlid, raise_if_not_found=False)
                if step and step.plan_id == plan and step.summary == source_summary:
                    step.summary = localized_summary

        if self.env['res.lang'].search_count([('code', '=', 'zh_CN')]):
            self.env.ref('hr.menu_config_plan_plan').with_context(lang='zh_CN').name = '员工计划'
