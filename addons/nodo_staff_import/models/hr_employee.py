import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import SQL
from odoo.tools.sql import escape_like_value


def field_error(field, message):
    error = ValidationError(message)
    error.context = {'supplement_field': field}
    return error


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

    # A form adapter for ordinary read/write. The employee and version remain
    # the only stored records for these values.
    nodo_supplement = fields.Json(
        string='补充员工信息', compute='_compute_nodo_supplement', inverse='_inverse_nodo_supplement',
        compute_sudo=False, groups='base.group_system',
    )

    def _supplement_values(self):
        return {
            'name': self.name or '', 'number': self.nodo_personnel_number or '',
            'department': self.department_id.id or False, 'job': self.job_id.name or '',
        }

    @api.depends('name', 'nodo_personnel_number', 'department_id', 'job_id.name', 'additional_note', 'category_ids.name')
    @api.depends_context('uid', 'company', 'version_id', 'lang')
    def _compute_nodo_supplement(self):
        pending = self.env.ref('__import__.nodo_staff_roster_pending_review', raise_if_not_found=False)
        for employee in self:
            source = re.search(r'(?m)^架构图来源编号[ \t]+([^\r\n]+)', employee.additional_note or '')
            tags = employee.category_ids
            pending_tag = (pending and pending & tags) or tags.filtered(lambda tag: tag.name == '待复核')[:1]
            reviewed_tag = tags.filtered(lambda tag: tag.name == '已复核')[:1]
            employee.nodo_supplement = {
                **employee._supplement_values(),
                'sourceNumber': source.group(1).strip() if source else '',
                'review': 'pending' if pending_tag else 'complete' if reviewed_tag else 'unknown',
                'reviewLabel': (pending_tag or reviewed_tag).name or '暂无复核记录',
                'canEditName': employee.has_access('write') and employee.has_field_access(employee._fields['name'], 'write'),
            }

    def _inverse_nodo_supplement(self):
        for employee in self:
            employee.check_access('write')
            payload = employee.nodo_supplement
            current = employee._supplement_values()
            changes = payload.get('changes') if isinstance(payload, dict) else None
            original = payload.get('original') if isinstance(payload, dict) else None
            if not isinstance(changes, dict) or not isinstance(original, dict) or changes.keys() - current.keys():
                raise ValidationError('请重新打开员工档案')
            if not changes:
                continue
            if 'job' in changes and original.get('department') != current['department']:
                raise field_error('department', '部门已变更，请重新打开档案核对')
            for field, value in changes.items():
                if field == 'department':
                    if type(value) is not int or value <= 0:
                        raise field_error(field, '请选择部门')
                elif not isinstance(value, str):
                    raise field_error(field, '请输入文字')
                if original.get(field) != current[field]:
                    raise field_error(field, '此项已被修改，请重新打开档案核对')
            values = {**current, **{key: value.strip() if isinstance(value, str) else value for key, value in changes.items()}}
            if not values['name']:
                raise field_error('name', '请填写姓名')
            if not values['department']:
                raise field_error('department', '请选择部门')
            department = employee.department_id
            write_values = {}
            if 'department' in changes:
                department = self.env['hr.department'].search([
                    ('id', '=', values['department']), ('company_id', 'in', [False, employee.company_id.id]),
                ], limit=1)
                if not department:
                    raise field_error('department', '请选择可用的部门')
                write_values['department_id'] = department.id
            if 'name' in changes:
                write_values['name'] = values['name']
            if 'number' in changes:
                number = values['number']
                if number:
                    # Share the importer's serialization point for employee numbers.
                    self.env.cr.execute(SQL('UPDATE res_company SET write_date = write_date WHERE id = %s', employee.company_id.id))
                    duplicate = self.with_context(active_test=False).search_count([
                        ('id', '!=', employee.id), ('company_id', '=', employee.company_id.id),
                        ('nodo_personnel_number', '=ilike', escape_like_value(number)),
                    ], limit=1)
                    if duplicate:
                        raise field_error('number', '此编号已被使用')
                write_values['nodo_personnel_number'] = number or False
            if 'job' in changes:
                job_name = values['job']
                job = self.env['hr.job']
                if job_name:
                    job = job.with_context(active_test=False).search([
                        ('company_id', '=', employee.company_id.id), ('department_id', '=', department.id),
                        ('name', '=', job_name),
                    ], limit=1)
                    if job and not job.active:
                        raise field_error('job', '此岗位已归档，请核对岗位名称')
                    if not job:
                        job = job.create({'company_id': employee.company_id.id, 'department_id': department.id, 'name': job_name})
                write_values['job_id'] = job.id
            employee.write(write_values)
            employee.invalidate_recordset(['nodo_supplement'], flush=False)
