from odoo import fields, models


class HrDepartment(models.Model):
    _inherit = 'hr.department'

    # Materialize the native path so SQL can sort across all directory pages.
    nodo_directory_path = fields.Char(related='complete_name', store=True)
