import re

from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError, LockError, UserError, ValidationError
from odoo.fields import Command
from odoo.tools import SQL
from odoo.tools.sql import escape_like_value


PENDING_REVIEW_XMLID = '__import__.nodo_staff_roster_pending_review'


def field_error(field, message, employee_id=None):
    error = ValidationError(message)
    error.context = {'supplement_field': field}
    if employee_id:
        error.context['employee_id'] = employee_id
    return error


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    nodo_department_path = fields.Char(string='部门', related='department_id.nodo_directory_path')
    nodo_department_level = fields.Integer(compute='_compute_nodo_department_level')

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
    nodo_review_state = fields.Selection(
        [('pending', '待复核'), ('complete', '已复核'), ('unknown', '暂无复核记录')],
        string='档案状态', compute='_compute_nodo_review_state', groups='base.group_system',
    )
    nodo_account_state = fields.Selection(
        [('none', '未开通'), ('active', '已开通'), ('disabled', '已停用')],
        string='账号状态', compute='_compute_nodo_account_state', groups='base.group_system',
    )

    @api.depends('department_id.parent_path')
    def _compute_nodo_department_level(self):
        for employee in self:
            employee.nodo_department_level = (employee.department_id.parent_path or '').count('/')

    def _nodo_review_badge(self, pending):
        self.ensure_one()
        tags = self.category_ids
        pending_tag = (pending and pending & tags) or tags.filtered(lambda tag: tag.name == '待复核')[:1]
        if pending_tag:
            return 'pending', pending_tag.name
        reviewed_tag = tags.filtered(lambda tag: tag.name == '已复核')[:1]
        return ('complete', reviewed_tag.name) if reviewed_tag else ('unknown', '暂无复核记录')

    @api.depends('category_ids.name')
    def _compute_nodo_review_state(self):
        pending = self.env.ref(PENDING_REVIEW_XMLID, raise_if_not_found=False)
        for employee in self:
            employee.nodo_review_state = employee._nodo_review_badge(pending)[0]

    @api.depends('user_id', 'user_id.active')
    def _compute_nodo_account_state(self):
        for employee in self:
            employee.nodo_account_state = 'none' if not employee.user_id else 'active' if employee.user_id.active else 'disabled'

    def _supplement_values(self):
        return {
            'name': self.name or '', 'number': self.nodo_personnel_number or '',
            'department': self.department_id.id or False, 'job': self.job_id.name or '',
        }

    @api.depends('name', 'nodo_personnel_number', 'department_id', 'job_id.name', 'additional_note', 'category_ids.name')
    @api.depends_context('uid', 'company', 'version_id', 'lang')
    def _compute_nodo_supplement(self):
        pending = self.env.ref(PENDING_REVIEW_XMLID, raise_if_not_found=False)
        for employee in self:
            source = re.search(r'(?m)^架构图来源编号[ \t]+([^\r\n]+)', employee.additional_note or '')
            review, review_label = employee._nodo_review_badge(pending)
            employee.nodo_supplement = {
                **employee._supplement_values(),
                'sourceNumber': source.group(1).strip() if source else '',
                'review': review,
                'reviewLabel': review_label,
                'canEditName': employee.has_access('write') and employee.has_field_access(employee._fields['name'], 'write'),
            }

    def _nodo_employee_number_match(self, company, number, excluded_id=0):
        return self.with_context(active_test=False).search([
            ('id', '!=', excluded_id), ('company_id', '=', company.id),
            ('nodo_personnel_number', '=ilike', escape_like_value(number)),
        ], limit=1)

    def _nodo_check_add_member_access(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('只有具有员工建档权限的系统管理员可以添加成员。')
        self.check_access('create')

    @api.model
    def nodo_member_options(self):
        self._nodo_check_add_member_access()
        company_scope = [('company_id', 'in', [False, self.env.company.id]), ('active', '=', True)]
        departments = self.env['hr.department'].search_read(company_scope, ['complete_name'])
        departments.sort(key=lambda department: (department['complete_name'], department['id']))
        jobs = self.env['hr.job'].search_read(
            company_scope + [('department_id', 'in', [department['id'] for department in departments])],
            ['name', 'department_id'], order='name, id',
        )
        return {'departments': departments, 'jobs': jobs}

    @api.model
    def _nodo_pending_review_tag(self):
        known_tag = self.env.ref(PENDING_REVIEW_XMLID, raise_if_not_found=False)
        if known_tag:
            return known_tag
        tags = self.env['hr.employee.category']
        tag = tags.search([('name', '=', '待复核')], limit=1) or tags.create({'name': '待复核', 'color': 2})
        self.env['ir.model.data']._update_xmlids([{
            'xml_id': PENDING_REVIEW_XMLID, 'record': tag, 'noupdate': True,
        }])
        return tag

    @api.model
    def nodo_add_member(self, values, confirm_same_name=False):
        self._nodo_check_add_member_access()
        if not isinstance(values, dict) or values.keys() - {'name', 'number', 'department', 'job'}:
            raise ValidationError('请重新打开添加成员。')
        name = values.get('name')
        number = values.get('number', '')
        if not isinstance(name, str) or not name.strip():
            raise field_error('name', '请填写姓名')
        if not isinstance(number, str):
            raise field_error('number', '请输入人员编号')
        name, number = name.strip(), number.strip()
        company = self.env.company
        department_id, job_id = values.get('department'), values.get('job', False)
        if type(department_id) is not int or department_id <= 0:
            raise field_error('department', '请选择部门')
        department = self.env['hr.department'].search([
            ('id', '=', department_id), ('company_id', 'in', [False, company.id]), ('active', '=', True),
        ], limit=1)
        if not department:
            raise field_error('department', '请选择当前公司可用的部门')
        if job_id is not False:
            if type(job_id) is not int or job_id <= 0 or not self.env['hr.job'].search_count([
                ('id', '=', job_id), ('department_id', '=', department.id),
                ('company_id', 'in', [False, company.id]), ('active', '=', True),
            ], limit=1):
                raise field_error('job', '请选择该部门的可用岗位')

        # The same serialization point is used by roster import and employee edits.
        self.env.cr.execute(SQL('UPDATE res_company SET write_date = write_date WHERE id = %s', company.id))
        if number:
            duplicate = self._nodo_employee_number_match(company, number)
            if duplicate:
                raise field_error('number', '此人员编号已被使用', duplicate.id)
        if confirm_same_name is not True:
            matches = self.with_context(active_test=False).search([
                ('company_id', '=', company.id), ('name', '=ilike', escape_like_value(name)),
            ], limit=5)
            if matches:
                return {'matches': [{
                    'id': match.id,
                    'department': match.department_id.complete_name or '未设置部门',
                    'number': match.nodo_personnel_number or '未填工号',
                } for match in matches]}
        # Resource creation honors context defaults even if the employee passes user_id=False.
        creation_context = {key: value for key, value in self.env.context.items() if not key.startswith('default_')}
        employee = self.with_context(creation_context).create({
            'name': name, 'company_id': company.id, 'department_id': department.id,
            'nodo_personnel_number': number or False, 'job_id': job_id,
            'category_ids': [Command.link(self._nodo_pending_review_tag().id)], 'user_id': False,
        })
        return {'id': employee.id, 'name': employee.name}

    def _nodo_check_open_member_account(self, *, lock=False):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('只有系统管理员可以开通员工账号。')
        self.check_access('write')
        self.env['res.users'].check_access('create')
        if lock:
            try:
                self.lock_for_update(allow_referencing=True)
            except LockError as error:
                raise ValidationError('该员工的账号正在开通，请稍后重试。') from error
            self.invalidate_recordset(['user_id'])
        if self.user_id:
            raise ValidationError('该员工已关联账号，请打开已有账号查看。')

    def action_nodo_open_member_account(self):
        self._nodo_check_open_member_account()
        return {
            'type': 'ir.actions.client', 'tag': 'nodo_staff_open_account', 'name': '开通账号',
            'params': {
                'id': self.id, 'name': self.name,
                'number': self.nodo_personnel_number or '',
                'department': self.department_id.complete_name or '',
            },
        }

    def nodo_create_member_account(self, login):
        self._nodo_check_open_member_account(lock=True)
        if not isinstance(login, str) or not login.strip():
            raise field_error('login', '请填写登录名')

        company = self.company_id
        context = {key: value for key, value in self.env.context.items() if not key.startswith('default_')}
        users = self.env['res.users'].with_context(context, no_reset_password=True).with_company(company)
        try:
            with self.env.cr.savepoint():
                user = users.create({
                    'name': self.name,
                    'login': login.strip(),
                    'create_employee_id': self.id,
                    'partner_id': self.work_contact_id.id or False,
                    'company_id': company.id,
                    'company_ids': [Command.set(company.ids)],
                    'group_ids': [Command.set([self.env.ref('base.group_user').id])],
                })
        except UniqueViolation as error:
            if error.diag.constraint_name == 'res_users_login_key':
                raise field_error('login', '此登录名已被使用') from error
            raise
        return {'id': user.id}

    def action_send_invitation(self):
        raise UserError('请在员工详情的「设置」中开通或管理账号。')

    def action_copy_invitation_link(self):
        raise UserError('请在员工详情的「设置」中开通或管理账号。')

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
                    if self._nodo_employee_number_match(employee.company_id, number, employee.id):
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
