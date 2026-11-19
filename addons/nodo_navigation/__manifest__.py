{
    'name': 'NODO 应用导航',
    'version': '20.0.1.1.0',
    'summary': '按账号权限显示应用侧栏和功能搜索',
    'author': 'NODO',
    'license': 'Other proprietary',
    'category': 'Hidden',
    'depends': ['nodo_base'],
    'assets': {
        'web.assets_backend': [
            'nodo_navigation/static/src/menu_groups.js',
            'nodo_navigation/static/src/quick_jump_search.js',
            'nodo_navigation/static/src/quick_jump_dialog.js',
            'nodo_navigation/static/src/quick_jump_dialog.xml',
            'nodo_navigation/static/src/quick_jump_dialog.scss',
            'nodo_navigation/static/src/application_sidebar.js',
            'nodo_navigation/static/src/application_sidebar.xml',
            'nodo_navigation/static/src/application_sidebar.scss',
        ],
    },
    'installable': True,
    'application': False,
}
