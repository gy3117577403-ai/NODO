{
    'name': 'NODO Contract',
    'summary': '单柜选型、报价核算、审批及转销售订单',
    'version': '20.0.2.1.0',
    'category': 'Sales',
    'author': 'NODO',
    'license': 'Other proprietary',
    'depends': ['nodo_base', 'sale_management'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/ir.access.csv',
        'views/product_views.xml',
        'views/drawing_views.xml',
        'views/quote_views.xml',
        'data/drawing_cron.xml',
        'report/customer_quote.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nodo_contract/static/src/selection/vision.js',
            'nodo_contract/static/src/selection/selection.js',
            'nodo_contract/static/src/selection/selection.xml',
            'nodo_contract/static/src/selection/selection.scss',
        ],
    },
    'installable': True,
}
