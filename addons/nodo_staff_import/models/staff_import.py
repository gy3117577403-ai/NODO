import csv
import hashlib
import io
from collections import Counter, defaultdict
from typing import NamedTuple

from odoo import fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL


REQUIRED_HEADERS = ('人员编号', '姓名', '部门路径', '岗位', '复核')
ACTIONS = {'create': '新增', 'update': '更新', 'skip': '跳过', 'conflict': '冲突'}


class StaffRow(NamedTuple):
    number: str
    name: str
    department: tuple[str, ...]
    job: str
    review: str
    login: str


class StaffPlan(NamedTuple):
    row: StaffRow
    action: str
    note: str
    employee_id: int = 0
    user_id: int = 0
    snapshot: tuple = ()


def department_parts(path):
    return tuple(part.strip() for part in path.split(' / '))


class StaffImport(models.TransientModel):
    _name = 'nodo.staff.import'
    _description = '人员导入'

    company_id = fields.Many2one('res.company', string='目标公司', required=True, default=lambda self: self.env.company)
    roster_file = fields.Binary(string='人员确认表', attachment=False)
    roster_filename = fields.Char(string='文件名')
    state = fields.Selection(
        [('draft', '待预检'), ('preview', '预检结果'), ('done', '已导入')],
        default='draft', readonly=True, required=True,
    )
    summary = fields.Char(string='汇总', readonly=True)
    details = fields.Text(string='按条查看', readonly=True)
    preview_token = fields.Char(copy=False, readonly=True)
    has_changes = fields.Boolean(readonly=True)

    def _scoped_wizard(self):
        self.ensure_one()
        actor = self.env.user
        if not (actor._is_system() or actor._is_superuser()):
            raise AccessError('只有系统管理员可以预检或导入人员档案。')
        self.check_access('write')
        if self.company_id not in self.env.companies:
            raise AccessError('请切换到有权限的目标公司后再导入人员。')
        return self.sudo().with_company(self.company_id).with_context(active_test=False)

    def _read_roster(self):
        if not self.roster_file:
            raise UserError('请先选择人员确认表。')
        filename = (self.roster_filename or '').lower()
        if not filename.endswith(('.xlsx', '.csv')):
            raise UserError('请上传 Excel 工作簿（.xlsx）或 UTF-8 CSV 文件。')
        try:
            if filename.endswith('.xlsx'):
                reader = self.env['base_import.import'].new({'file': self.roster_file})
                _, data = reader._read_xlsx({})
            else:
                data = list(csv.reader(io.StringIO(self.roster_file.content.decode('utf-8-sig'))))
        except Exception as exc:
            raise UserError('无法读取确认表。请重新用 Excel 保存为 .xlsx 或 UTF-8 CSV 后上传。') from exc
        data = [[str(value if value is not None else '').strip() for value in line] for line in data]
        if not data:
            raise UserError('确认表中没有表头。')
        columns = data[0]
        missing = [header for header in REQUIRED_HEADERS if header not in columns]
        if missing:
            raise UserError('确认表缺少列：' + '、'.join(missing))
        if len([column for column in columns if column]) != len({column for column in columns if column}):
            raise UserError('确认表中有重复的列标题，请核对首行。')
        index_by_name = {column: index for index, column in enumerate(columns) if column}
        rows = []
        for line in data[1:]:
            if not any(line):
                continue
            by_name = {name: line[index] for name, index in index_by_name.items() if index < len(line)}
            rows.append(StaffRow(
                by_name.get('人员编号', ''), by_name.get('姓名', ''),
                department_parts(by_name.get('部门路径', '')), by_name.get('岗位', ''),
                by_name.get('复核', ''), by_name.get('已有登录名', ''),
            ))
        return rows

    def _plan_roster(self, rows):
        company_domain = [('company_id', '=', self.company_id.id)]
        employees = self.env['hr.employee'].search(company_domain)
        by_number = {person.nodo_personnel_number: person for person in employees if person.nodo_personnel_number}
        by_user = {person.user_id.id: person.id for person in employees if person.user_id}
        unnumbered_names = {person.name for person in employees if not person.nodo_personnel_number}
        departments = defaultdict(list)
        for department in self.env['hr.department'].search(company_domain):
            departments[department_parts(department.complete_name)].append(department)
        jobs = defaultdict(list)
        for job in self.env['hr.job'].search(company_domain):
            jobs[job.department_id.id, job.name].append(job)
        known_users = {
            user.login: user for user in self.env['res.users'].search([
                ('login', 'in', list({row.login for row in rows if row.login})),
            ])
        }
        number_count = Counter(row.number for row in rows if row.number)
        login_count = Counter(row.login for row in rows if row.login)
        plan = []
        for row in rows:
            def conflict(reason):
                return StaffPlan(row, 'conflict', reason)

            if row.review in ('', '待复核'):
                plan.append(StaffPlan(row, 'skip', '待复核'))
                continue
            if row.review != '通过':
                plan.append(conflict('复核列请填「通过」或「待复核」'))
                continue
            if not all((row.number, row.name, row.job)) or not all(row.department) or row.job == '未提供':
                plan.append(conflict('请补齐人员编号、姓名、完整部门路径和岗位'))
                continue
            if number_count[row.number] > 1:
                plan.append(conflict('表内人员编号重复'))
                continue
            person = by_number.get(row.number)
            if person and not person.active:
                plan.append(conflict('人员档案已归档，请先核对'))
                continue
            if not person and row.name in unnumbered_names:
                plan.append(conflict('已有同名未编号档案，请先在员工档案核对并补编号'))
                continue
            path_levels = [departments[row.department[:depth]] for depth in range(1, len(row.department) + 1)]
            if any(len(matches) > 1 or (matches and not matches[0].active) for matches in path_levels):
                plan.append(conflict('部门路径存在重名或归档记录，请先核对'))
                continue
            department_id = path_levels[-1][0].id if path_levels[-1] else 0
            job_entries = jobs.get((department_id, row.job), []) if department_id else []
            if len(job_entries) > 1 or (job_entries and not job_entries[0].active):
                plan.append(conflict('岗位存在重名或归档记录，请先核对'))
                continue
            job_id = job_entries[0].id if job_entries else 0
            user = known_users.get(row.login)
            if row.login:
                if not user or not user.active or not user._is_internal() or self.company_id not in user.company_ids:
                    plan.append(conflict('登录名须对应目标公司的在用内部账号'))
                    continue
                if login_count[row.login] > 1 or (user.id in by_user and (not person or by_user[user.id] != person.id)):
                    plan.append(conflict('该登录名已用于其他人员'))
                    continue
                if person and person.user_id and person.user_id != user:
                    plan.append(conflict('已有其他关联账号，请先在员工档案核对'))
                    continue
            current = (person.name, person.department_id.id, person.job_id.id, person.user_id.id) if person else ()
            user_id = user.id if user else (person.user_id.id if person else 0)
            target = (row.name, department_id, job_id, user_id or False)
            snapshot = (current, target, tuple(matches[0].id if matches else 0 for matches in path_levels))
            action = ('skip' if current == target else 'update') if person else 'create'
            note = '档案一致' if action == 'skip' else f'{" / ".join(row.department)} · {row.job}'
            if user and not (person and person.user_id):
                note += ' · 关联已有账号'
            plan.append(StaffPlan(
                row, action, note,
                person.id if person else 0, user_id or 0, snapshot,
            ))
        return plan

    def _preview_data(self):
        plan = self._plan_roster(self._read_roster())
        digest = repr((self.company_id.id, plan)).encode()
        token = hashlib.sha256(self.roster_file.content + digest).hexdigest()
        return plan, token

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window', 'name': '人员导入',
            'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new',
        }

    def action_preview(self):
        wizard = self._scoped_wizard()
        plan, token = wizard._preview_data()
        counts = Counter(entry.action for entry in plan)
        details = []
        for index, entry in enumerate(plan, start=1):
            row = entry.row
            label = f'{row.number} {row.name}'.strip() or '未填写编号和姓名'
            details.append(f'{index}. {ACTIONS[entry.action]} · {label}' + (f' · {entry.note}' if entry.note else ''))
        self.write({
            'state': 'preview', 'preview_token': token,
            'summary': '　'.join(f'{label} {counts[action]}' for action, label in ACTIONS.items()),
            'details': '\n'.join(details),
            'has_changes': bool(counts['create'] or counts['update']),
        })
        return self._reopen()

    def _save_plan(self, plan):
        Department = self.env['hr.department']
        Job = self.env['hr.job']
        Employee = self.env['hr.employee']
        company_id = self.company_id.id
        departments = {}
        jobs = {}
        for entry in plan:
            if entry.action not in ('create', 'update'):
                continue
            row = entry.row
            parent_id = False
            for depth, name in enumerate(row.department, start=1):
                parts = row.department[:depth]
                if parts not in departments:
                    existing_id = entry.snapshot[2][depth - 1]
                    departments[parts] = existing_id or Department.create({
                        'name': name, 'parent_id': parent_id, 'company_id': company_id,
                    }).id
                parent_id = departments[parts]
            job_key = (parent_id, row.job)
            if job_key not in jobs:
                jobs[job_key] = entry.snapshot[1][2] or Job.create({
                    'name': row.job, 'department_id': parent_id, 'company_id': company_id,
                }).id
            values = {
                'name': row.name, 'department_id': parent_id, 'job_id': jobs[job_key],
            }
            if entry.user_id:
                values['user_id'] = entry.user_id
            if entry.employee_id:
                employee = Employee.browse(entry.employee_id)
                employee.write({
                    key: value for key, value in values.items()
                    if (employee[key].id if key.endswith('_id') else employee[key]) != value
                })
            else:
                Employee.create({**values, 'company_id': company_id, 'nodo_personnel_number': row.number})

    def action_import(self):
        wizard = self._scoped_wizard()
        if self.state != 'preview' or not self.preview_token:
            raise UserError('请先预检并查看结果。')
        # Advance the company row version so a concurrent import retries with a fresh snapshot.
        self.env.cr.execute(SQL('UPDATE res_company SET write_date = write_date WHERE id = %s', self.company_id.id))
        plan, token = wizard._preview_data()
        if token != self.preview_token:
            raise UserError('确认表或目标公司的资料已经变化，请重新预检。')
        counts = Counter(entry.action for entry in plan)
        if not (counts['create'] or counts['update']):
            raise UserError('本批次没有可导入的新增或更新记录。')
        wizard._save_plan(plan)
        self.env['nodo.staff.import.batch'].sudo().create({
            'company_id': self.company_id.id,
            'roster_filename': self.roster_filename,
            'created_count': counts['create'], 'updated_count': counts['update'],
            'skipped_count': counts['skip'], 'conflict_count': counts['conflict'],
        })
        self.write({'state': 'done', 'has_changes': False, 'preview_token': False, 'roster_file': False})
        return self._reopen()


class StaffImportBatch(models.Model):
    _name = 'nodo.staff.import.batch'
    _description = '人员导入记录'
    _rec_name = 'roster_filename'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', string='目标公司', required=True, index=True)
    roster_filename = fields.Char(string='文件名')
    created_count = fields.Integer(string='新增')
    updated_count = fields.Integer(string='更新')
    skipped_count = fields.Integer(string='跳过')
    conflict_count = fields.Integer(string='冲突')
