{
    'name': 'NODO 技术工作台板料成本',
    'version': '20.0.1.0.0',
    'author': 'NODO',
    'category': 'Hidden',
    'summary': '技术工作台的板材选择和板料用量使用成本库的当前价格',
    'license': 'Other proprietary',
    'depends': ['nodo_draw', 'nodo_cost'],
    'assets': {'web.assets_backend': [
        'nodo_draw_cost/static/src/live_sheet_prices.js',
        'nodo_draw_cost/static/src/costed_sheets.js',
        'nodo_draw_cost/static/src/costed_sheets.xml',
        'nodo_draw_cost/static/src/costed_sheets.scss',
    ]},
    'auto_install': True,
    'installable': True,
}
