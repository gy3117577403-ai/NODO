from odoo import api, fields, models


class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    nodo_department_segments = fields.Json(compute='_compute_nodo_department_segments')

    @api.depends('department_id.parent_path', 'department_id.nodo_directory_path')
    @api.depends_context('uid', 'company')
    def _compute_nodo_department_segments(self):
        paths = self.department_id._nodo_directory_segments()
        for employee in self:
            employee.nodo_department_segments = paths.get(employee.department_id.id, [])

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        result = super().search_panel_select_range(field_name, **kwargs)
        if field_name == 'department_id' and result.get('values'):
            self.env['hr.department']._nodo_color_search_panel_values(result['values'])
        return result
