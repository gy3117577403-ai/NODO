# Executed by scripts/nodo.ps1 in an Odoo shell on the dedicated staff pilot database.
import hashlib
import json
import os
import re
from pathlib import Path

from odoo.fields import Command
from odoo.tools import SQL


PILOT_DB = 'nodo_staff_pilot'
SNAPSHOT_KEY = 'nodo_staff_import.pilot_snapshot_sha256'
DIRECTORY_HTML = Path('/mnt/nodo-roster.html')
REVIEW_TAG = '__import__.nodo_staff_roster_pending_review'


def read_roster():
    document = DIRECTORY_HTML.read_text(encoding='utf-8-sig')
    fragments = re.findall(
        r'<script\b[^>]*\bid=["\']directory-data["\'][^>]*>([\s\S]*?)</script\s*>',
        document,
        flags=re.IGNORECASE,
    )
    if len(fragments) != 1:
        raise SystemExit('架构图中应有一份人员目录数据')
    source = json.loads(fragments[0])
    units = {unit['id']: unit for unit in source['units']}
    roots = [unit for unit in units.values() if not unit['parentId']]
    if (
        len(units) != len(source['units']) or len(roots) != 1
        or roots[0]['kind'] != 'company' or roots[0]['name'] != source['company']
    ):
        raise SystemExit('无法确认唯一的公司及部门层级')

    ordered_units = []
    reached = {roots[0]['id']}
    while len(reached) < len(units):
        ready = [unit for unit in units.values() if unit['id'] not in reached and unit['parentId'] in reached]
        if not ready:
            raise SystemExit('部门层级存在缺少上级或循环引用的记录')
        ordered_units.extend(ready)
        reached.update(unit['id'] for unit in ready)

    codes = set()
    people = source['people']
    if not people:
        raise SystemExit('人员目录为空')
    for person in people:
        if not person['code'] or not person['name'].strip() or person['code'] in codes or person['demo']:
            raise SystemExit('人员目录存在缺少身份、来源编号重复或样例记录')
        assignments = person['assignments']
        if len(assignments) != 1 or assignments[0]['unitId'] not in units:
            raise SystemExit('无法确定一名人员的唯一部门，请核对架构图')
        codes.add(person['code'])
    snapshot = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return source['company'], roots[0]['id'], ordered_units, people, snapshot


def xmlid(kind, key):
    digest = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:32]
    return f'__import__.nodo_staff_roster_{kind}_{digest}'


def record_data(reference, **values):
    return {'xml_id': reference, 'noupdate': True, 'values': values}


def job_title(person):
    title = (person['assignments'][0]['title'] or '').strip()
    return '' if title == '未提供' else title


def load_roster(company, root_id, ordered_units, people):
    Employee = env['hr.employee'].with_company(company).with_context(active_test=False, tracking_disable=True)
    Department = env['hr.department'].with_company(company).with_context(active_test=False)
    Job = env['hr.job'].with_company(company).with_context(active_test=False)
    review_tag = env['hr.employee.category']._load_records([
        record_data(REVIEW_TAG, name='待复核'),
    ])

    department_ids = {root_id: False}
    for unit in ordered_units:
        department = Department._load_records([
            record_data(
                xmlid('department', unit['id']), name=unit['name'], company_id=company.id,
                parent_id=department_ids[unit['parentId']], active=unit['active'],
            ),
        ])
        department_ids[unit['id']] = department.id

    job_keys = dict.fromkeys(
        (person['assignments'][0]['unitId'], job_title(person)) for person in people if job_title(person)
    )
    jobs = Job._load_records([
        record_data(
            xmlid('job', [unit_id, title]), name=title, company_id=company.id,
            department_id=department_ids[unit_id],
        )
        for unit_id, title in job_keys
    ])
    job_ids = dict(zip(job_keys, jobs.ids, strict=True))
    employee_rows = []
    for person in people:
        unit_id = person['assignments'][0]['unitId']
        employee_rows.append(record_data(
            xmlid('employee', person['code']), name=person['name'], company_id=company.id,
            department_id=department_ids[unit_id], job_id=job_ids.get((unit_id, job_title(person)), False),
            active=person['active'], user_id=False,
            category_ids=[Command.set(review_tag.ids if person['needsReview'] else [])],
            additional_note=f"架构图来源编号 {person['code']}\n请核对正式人员编号、部门和岗位。",
        ))
    employees = Employee._load_records(employee_rows)
    for employee, person in zip(employees, people, strict=True):
        unit_id = person['assignments'][0]['unitId']
        if (
            employee.name != person['name'] or employee.company_id != company
            or employee.department_id.id != department_ids[unit_id]
            or employee.job_id.id != job_ids.get((unit_id, job_title(person)), False)
            or employee.active != person['active'] or (review_tag in employee.category_ids) != person['needsReview']
            or employee.user_id or employee.nodo_personnel_number
        ):
            raise SystemExit('入档结果与人员源记录不一致，整批取消')
    return employees, review_tag


def import_staff_pilot():
    if env.cr.dbname != PILOT_DB:
        raise SystemExit('真实架构图只允许进入独立人员试点库')
    company_name, root_id, ordered_units, people, snapshot = read_roster()
    company = env.ref('base.main_company')
    env.cr.execute(SQL('UPDATE res_company SET write_date = write_date WHERE id = %s', company.id))
    params = env['ir.config_parameter']
    previous = params.get_str(SNAPSHOT_KEY)
    if previous and previous != snapshot:
        raise SystemExit('试点库已有另一版架构图，请先对照现有档案')

    accounts_before = env['res.users'].with_context(active_test=False).search_count([])
    if not previous:
        existing_ids = env['ir.model.data'].search_count([
            ('module', '=', '__import__'), ('name', '=like', 'nodo_staff_roster_%'),
        ])
        if company.name != 'NODO' or existing_ids:
            raise SystemExit('试点公司已配置，请先核对当前数据来源')
        company.name = company_name
        employees, review_tag = load_roster(company, root_id, ordered_units, people)
        params.set_str(SNAPSHOT_KEY, snapshot)
        env['nodo.staff.import.batch'].with_user(env.ref('base.user_admin')).sudo().create({
            'company_id': company.id, 'roster_filename': '组织架构图.html', 'created_count': len(employees),
        })
    else:
        review_tag = env.ref(REVIEW_TAG)
        employees = env['hr.employee'].concat(*[env.ref(xmlid('employee', person['code'])) for person in people])

    if len(employees) != len(people):
        raise SystemExit('试点档案数量与架构图不一致')
    accounts_delta = env['res.users'].with_context(active_test=False).search_count([]) - accounts_before
    if accounts_delta:
        raise SystemExit('账号数量发生变化，整批取消')
    stats = {
        'people': len(employees),
        'created': 0 if previous else len(employees),
        'departments': len(ordered_units),
        'pending': sum(review_tag in employee.category_ids for employee in employees),
        'missing_job': sum(not employee.job_id for employee in employees),
        'linked_accounts': sum(bool(employee.user_id) for employee in employees),
        'account_change': accounts_delta,
    }
    if os.environ.get('NODO_STAFF_PILOT_COMMIT') == '1':
        env.cr.commit()
        print('NODO_STAFF_PILOT_IMPORTED', json.dumps(stats))
    else:
        env.cr.rollback()
        print('NODO_STAFF_PILOT_PREVIEW', json.dumps(stats))


import_staff_pilot()
