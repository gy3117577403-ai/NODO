from ast import literal_eval
from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # Materialize the native path so SQL can sort across all directory pages.
    nodo_directory_path = fields.Char(related='complete_name', store=True)
    nodo_directory_branch_id = fields.Many2one(
        'hr.department', string='部门筛选',
        compute='_compute_nodo_directory_branch_id', search='_search_nodo_directory_branch_id',
    )
    nodo_directory_segments = fields.Json(compute='_compute_nodo_directory_segments')
    nodo_direct_staff_count = fields.Integer(compute='_compute_nodo_staff_counts')
    nodo_branch_staff_count = fields.Integer(compute='_compute_nodo_staff_counts')
    nodo_has_subdepartments = fields.Boolean(compute='_compute_nodo_has_subdepartments')

    def _compute_nodo_directory_branch_id(self):
        for department in self:
            department.nodo_directory_branch_id = department

    @api.model
    def _search_nodo_directory_branch_id(self, operator, value):
        return [('id', operator, value)]

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        if field_name != 'nodo_directory_branch_id':
            return super().search_panel_select_range(field_name, **kwargs)
        kwargs.update(
            expand=True,
            enable_counters=False,
            limit=kwargs.get('limit') or None,
            comodel_domain=Domain(kwargs.get('comodel_domain', [])) & Domain('has_read_access', '=', True),
        )
        result = super().search_panel_select_range(field_name, **kwargs)
        self._nodo_color_search_panel_values(result.get('values', []))
        return result

    @api.depends('parent_path', 'nodo_directory_path')
    @api.depends_context('uid', 'company')
    def _compute_nodo_directory_segments(self):
        paths = self._nodo_directory_segments()
        for department in self:
            department.nodo_directory_segments = paths[department.id]

    def _nodo_department_employee_model(self):
        employee = self.env['hr.employee']
        return employee if employee.has_access('read') else self.env['hr.employee.public']

    def _nodo_department_employee_domain(self, include_children):
        return [('active', '=', True), ('department_id', 'child_of' if include_children else 'in', self.ids)]

    @api.depends('parent_path', 'member_ids.active', 'child_ids')
    @api.depends_context('uid', 'company')
    def _compute_nodo_staff_counts(self):
        employees = self._nodo_department_employee_model()
        groups = employees._read_group(self._nodo_department_employee_domain(True), ['department_id'], ['__count'])
        direct_counts = {}
        branch_counts = defaultdict(int)
        for department, count in groups:
            direct_counts[department.id] = count
            for identifier in (department.parent_path or '').split('/'):
                if identifier:
                    branch_counts[int(identifier)] += count
        for department in self:
            department.nodo_direct_staff_count = direct_counts.get(department.id, 0)
            department.nodo_branch_staff_count = branch_counts[department.id]

    @api.depends('child_ids')
    @api.depends_context('uid', 'company')
    def _compute_nodo_has_subdepartments(self):
        parents = self.with_context(active_test=False).search_fetch(
            [('parent_id', 'in', self.ids), ('has_read_access', '=', True)], ['parent_id'],
        ).parent_id
        for department in self:
            department.nodo_has_subdepartments = department in parents

    def action_nodo_view_department_staff(self):
        self.ensure_one()
        self.check_access('read')
        if not self.with_context(active_test=False).search_count([
            ('id', '=', self.id), ('has_read_access', '=', True),
        ]):
            raise AccessError(self.env._('你没有查看此部门员工的权限。'))

        model = self._nodo_department_employee_model()
        action_id = 'hr.open_view_employee_list_my' if model._name == 'hr.employee' else 'hr.hr_employee_public_action'
        action = self.env['ir.actions.actions']._for_xml_id(action_id)
        direct_only = self.env.context.get('nodo_department_direct') is True
        context = literal_eval(action.get('context') or '{}')
        context.update(default_department_id=self.id, searchpanel_default_department_id=self.id)
        action.update(
            name=f"{self.name} · {'仅直属' if direct_only else '含下级'}",
            domain=self._nodo_department_employee_domain(not direct_only),
            context=context,
            help='<p>当前范围暂无员工</p>',
        )
        return action

    def _nodo_directory_nodes(self):
        # Use the whole accessible organization so a filtered list uses the same palette as the tree.
        departments = self.with_context(active_test=False).search_fetch([], ['name', 'parent_id', 'company_id'], order='id')
        company_positions = defaultdict(int)
        nodes = {}
        for department in departments:
            company_id = department.company_id.id
            company_positions[company_id] += 1
            is_main_office = not department.parent_id and department.name == '总经办'
            nodes[department.id] = {
                'id': department.id,
                'name': department.name,
                'color': 0 if is_main_office else company_positions[company_id],
            }
        return nodes

    def _nodo_directory_segments(self):
        if not self:
            return {}
        nodes = self._nodo_directory_nodes()
        paths = {}
        for department in self:
            identifiers = (department.parent_path or '').split('/')
            segments = [nodes.get(int(identifier)) for identifier in identifiers if identifier]
            paths[department.id] = segments if all(segments) else []
        return paths

    def _nodo_color_search_panel_values(self, values):
        nodes = self._nodo_directory_nodes()
        for value in values:
            if value['id'] in nodes:
                value['nodo_color'] = nodes[value['id']]['color']
