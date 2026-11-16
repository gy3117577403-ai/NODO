{
    'name': 'NODO Base',
    'version': '20.0.1.0.0',
    'summary': 'NODO 品牌、主题与角色',
    'description': """
NODO 基础模块（必装）：品牌、界面主题、七类角色组。
不授予应用级权限，应用权限由各业务模块落实，见 docs/权限矩阵.md。
""",
    'category': 'Hidden',
    'author': 'NODO',
    'license': 'Other proprietary',
    'depends': ['base', 'web', 'mail', 'base_setup', 'base_install_request'],
    'data': [
        'security/nodo_roles.xml',
        'data/ir_config_parameter.xml',
        'views/webclient_templates.xml',
        'views/mail_templates.xml',
        'views/apps_menu.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            ('prepend', 'nodo_base/static/src/scss/primary_variables.scss'),
        ],
        'web.assets_frontend': [
            'nodo_base/static/src/scss/login.scss',
        ],
        'web.assets_backend': [
            'nodo_base/static/src/js/*.js',
            'nodo_base/static/src/xml/*.xml',
        ],
    },
    'installable': True,
    'application': False,
}
