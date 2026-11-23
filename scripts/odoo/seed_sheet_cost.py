if env.cr.dbname != 'nodo_dev':
    raise RuntimeError('板料测试价仅供本机开发库使用')

design = env['nodo.draw.design'].search([('source', '=', 'AE-202'), ('company_id', '=', env.company.id)], limit=1)
if not design:
    raise RuntimeError('当前公司缺少 AE-202 样柜')

prices = env['nodo.cost.sheet.price'].with_context(active_test=False)
created = 0
for category, gauge in [('cold_rolled', 1.5), ('cold_rolled', 2.0), ('galvanized', 2.5)]:
    if not prices.search_count([('company_id', '=', design.company_id.id), ('category', '=', category),
                                ('grade', '=', False), ('supply_condition', '=', False), ('thickness_mm', '=', gauge)]):
        prices.create(dict(company_id=design.company_id.id, category=category, thickness_mm=gauge, price_per_kg=5,
                           basis='trial', source_note='AE-202 样柜试算'))
        created += 1
env.cr.commit()
print(f'AE-202 板料测试价新增 {created} 条。')
