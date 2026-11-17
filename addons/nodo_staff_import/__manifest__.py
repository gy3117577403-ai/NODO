{
    'name': 'NODO 员工接入',
    'version': '20.0.1.0.0',
    'summary': '预检和导入员工档案，关联现有账号',
    'author': 'NODO',
    'license': 'Other proprietary',
    'category': 'Human Resources',
    'depends': ['nodo_base', 'hr', 'base_import'],
    'data': [
        'security/ir.access.csv',
        'views/staff_import_views.xml',
    ],
    'installable': True,
    'application': False,
}
