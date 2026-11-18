from collections import defaultdict

from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # Materialize the native path so SQL can sort across all directory pages.
    nodo_directory_path = fields.Char(related='complete_name', store=True)

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
