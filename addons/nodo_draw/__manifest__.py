{
    'name': 'NODO 技术工作台',
    'author': 'NODO',
    'version': '20.0.1.2.0',
    'category': 'Manufacturing',
    'summary': '从附件清单到 AE 柜装配与工程图纸',
    'license': 'Other proprietary',
    'depends': ['nodo_base'],
    'data': [
        'security/ir.access.csv',
        'views/workbench.xml',
    ],
    'assets': {'web.assets_backend': [
        'nodo_draw/static/src/mesh.js',
        'nodo_draw/static/src/workbench.js',
        'nodo_draw/static/src/workbench.xml',
        'nodo_draw/static/src/workbench.scss',
    ], 'nodo_draw.assets_ae': [
        'nodo_draw/static/lib/ae/viewport.min.js',
    ]},
    'application': True,
    'installable': True,
}
