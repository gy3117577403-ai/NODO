{
    'name': 'NODO 成本库',
    'version': '20.0.3.0.0',
    'author': 'NODO',
    'category': 'Manufacturing',
    'summary': '维护板料成本、辅料档案和辅材单价',
    'license': 'Other proprietary',
    'depends': ['nodo_base', 'bus'],
    'data': ['security/ir.access.csv', 'views/sheet_price.xml', 'views/auxiliary_price.xml',
             'views/auxiliary_library.xml'],
    'application': True,
    'installable': True,
}
