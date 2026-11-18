{
    'name': 'NODO 员工讨论接入',
    'version': '20.0.1.0.0',
    'summary': '按员工部门和角色查找同事，直接添加讨论成员',
    'author': 'NODO',
    'license': 'Other proprietary',
    'category': 'Productivity/Discuss',
    'depends': ['nodo_base', 'hr'],
    'assets': {
        'web.assets_backend': [
            'nodo_staff_discuss/static/src/staff_people.js',
            'nodo_staff_discuss/static/src/staff_people.xml',
            'nodo_staff_discuss/static/src/staff_people.scss',
        ],
    },
    'installable': True,
    'application': False,
}
