# Read-only roster verification for the dedicated personnel pilot.
import hashlib
import json


def source_records(model, kind):
    mappings = env['ir.model.data'].search([
        ('module', '=', '__import__'), ('model', '=', model._name),
        ('name', '=like', f'nodo_staff_roster_{kind}_%'),
    ])
    ids = mappings.mapped('res_id')
    records = model.browse(ids).exists()
    if len(records) != len(set(ids)) or len(ids) != len(set(ids)):
        raise SystemExit('架构图的来源档案存在缺失或重复关联')
    return records


def avatar_digest(people):
    image_checksums = []
    for person in people:
        value = person.image_1920
        content = getattr(value, 'content', value) or b''
        if isinstance(content, str):
            content = content.encode()
        image_checksums.append([person.id, hashlib.sha256(content).hexdigest()])
    return hashlib.sha256(json.dumps(image_checksums).encode()).hexdigest()


def check_roster():
    if env.cr.dbname != 'nodo_staff_pilot':
        raise SystemExit('请在独立人员试点库核对架构图档案')
    env.cr.rollback()
    env.cr.execute('SET TRANSACTION READ ONLY')
    company = env.ref('base.main_company')
    batch = env['nodo.staff.import.batch'].search([
        ('company_id', '=', company.id), ('roster_filename', '=', '组织架构图.html'),
    ], order='id desc', limit=1)
    snapshot = env['ir.config_parameter'].get_str('nodo_staff_import.pilot_snapshot_sha256')
    if not snapshot or not batch:
        raise SystemExit('试点库没有可核对的组织架构图导入批次')

    people = env['hr.employee'].with_context(active_test=False).search([('company_id', '=', company.id)], order='id')
    departments = env['hr.department'].with_context(active_test=False).search([('company_id', '=', company.id)], order='id')
    source_people = source_records(people.browse(), 'employee')
    source_departments = source_records(departments.browse(), 'department')
    if len(source_people) != batch.created_count or source_people - people or source_departments - departments:
        raise SystemExit('导入批次的员工数量或公司归属需要核对')

    active_people = people.filtered('active')
    active_departments = departments.filtered('active')
    additional_departments = active_departments - source_departments
    review_tag = env.ref('__import__.nodo_staff_roster_pending_review')
    users = env['res.users'].with_context(active_test=False).search([], order='id')
    content = {
        'company': [company.id, company.name],
        'snapshot': snapshot,
        'batch': [batch.id, batch.created_count],
        'source_people': sorted(source_people.ids),
        'source_departments': sorted(source_departments.ids),
        'people': [
            [person.id, person.name, person.active, person.department_id.id,
             person.job_id.id, person.job_id.name, person.job_title, person.parent_id.id,
             person.user_id.id, person.nodo_personnel_number, sorted(person.category_ids.ids)]
            for person in people
        ],
        'departments': [[dept.id, dept.name, dept.parent_id.id, dept.active] for dept in departments],
        'users': [[user.id, user.active, user.login, sorted(user.group_ids.ids)] for user in users],
    }
    directory = env.ref('nodo_staff_import.staff_member_directory_list', raise_if_not_found=False)
    detail = env.ref('nodo_staff_import.staff_employee_detail_form', raise_if_not_found=False)
    views = {mode: view_id for view_id, mode in env.ref('hr.open_view_employee_list_my').views}
    report = {
        'source_people': len(source_people),
        'source_departments': len(source_departments),
        'active_people': len(active_people),
        'active_departments': len(active_departments),
        'additional_departments': len(additional_departments),
        'people_in_additional_departments': sum(person.department_id in additional_departments for person in active_people),
        'root_departments': sum(not department.parent_id for department in active_departments),
        'department_levels': sorted({(department.parent_path or '').count('/') for department in active_departments}),
        'department_managers': len(active_departments.manager_id & active_people),
        'leader_titles': {
            title: sum((person.job_title or '').strip().endswith(title) for person in active_people)
            for title in ('组长', '主管')
        },
        'no_department': sum(not person.department_id for person in active_people),
        'pending': sum(review_tag in person.category_ids for person in active_people),
        'missing_job': sum(not (person.job_id or person.job_title) for person in active_people),
        'missing_number': sum(not person.nodo_personnel_number for person in active_people),
        'linked_accounts': sum(bool(person.user_id) for person in active_people),
        'new_directory_view': bool(directory and views.get('list') == directory.id),
        'new_detail_view': bool(detail and views.get('form') == detail.id),
        'data_sha256': hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'avatars_sha256': avatar_digest(people),
    }
    env.cr.rollback()
    print('NODO_STAFF_PILOT_CHECK', json.dumps(report))


check_roster()
