{
    'name': 'NODO Base',
    'version': '20.0.1.0.0',
    'summary': 'NODO 品牌、主题与角色',
    'description': """
NODO 基础模块（必装）：品牌、界面主题、八类角色组。
不授予应用级权限，应用权限由各业务模块落实，见 docs/权限矩阵.md。
""",
    'category': 'Hidden',
    'author': 'NODO',
    'license': 'Other proprietary',
    'depends': ['base', 'web', 'mail', 'mail_bot', 'base_setup', 'base_install_request'],
    'data': [
        'security/nodo_roles.xml',
        'data/ir_config_parameter.xml',
        'data/auth_defaults.xml',
        'data/discuss_channels.xml',
        'views/webclient_templates.xml',
        'views/mail_templates.xml',
        'views/apps_menu.xml',
        'views/discuss_channel_views.xml',
        'views/res_users_views.xml',
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
            'nodo_base/static/src/scss/material.scss',
            'nodo_base/static/src/scss/discuss.scss',
        ],
        'web.assets_unit_tests': [
            'nodo_base/static/tests/record_cards.test.js',
        ],
    },
    'installable': True,
    'application': False,
}
