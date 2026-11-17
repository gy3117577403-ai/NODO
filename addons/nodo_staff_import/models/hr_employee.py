from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    nodo_personnel_number = fields.Char(
        string='人员编号', copy=False, index='btree_not_null', groups='base.group_system',
        help='公司内唯一的稳定编号，用于后续名单导入匹配。',
    )

    _nodo_personnel_number_company = models.Constraint(
        'UNIQUE(company_id, nodo_personnel_number)',
        '同一公司内的人员编号必须唯一。',
    )
