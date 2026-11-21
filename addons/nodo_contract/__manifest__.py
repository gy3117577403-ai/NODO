{
    'name': 'NODO Contract',
    'summary': '单柜选型、报价核算、审批及转销售订单',
    'version': '20.0.1.0.0',
    'category': 'Sales',
    'author': 'NODO',
    'license': 'Other proprietary',
    'depends': ['nodo_base', 'sale_management'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/ir.access.csv',
        'views/product_views.xml',
        'views/quote_views.xml',
        'report/customer_quote.xml',
    ],
    'application': True,
    'installable': True,
}
