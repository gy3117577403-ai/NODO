{
    'name': 'NODO Supply',
    'version': '20.0.1.0.0',
    'summary': '采购单协作与员工个人权限',
    'author': 'NODO',
    'license': 'Other proprietary',
    'category': 'Inventory/Purchase',
    'depends': ['nodo_base_purchase', 'purchase_stock'],
    'data': [
        'security/purchase_roles.xml',
        'security/ir.access.csv',
        'views/res_users_views.xml',
        'views/purchase_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': ['nodo_supply/static/src/js/purchase_views.js'],
    },
    'installable': True,
    'application': True,
}
