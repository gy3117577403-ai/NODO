from odoo.addons.nodo_draw_cost.auxiliary_rules import HINGE, ITEMS, RING, SEAL

if env.cr.dbname != 'nodo_dev':
    raise RuntimeError('辅材参考价仅供本机开发库使用')

design = env['nodo.draw.design'].search([('source', '=', 'AE-202'), ('company_id', '=', env.company.id)], limit=1)
if not design:
    raise RuntimeError('当前公司缺少 AE-202 样柜')

prices = env['nodo.cost.auxiliary.price'].with_context(active_test=False)
by_variant = {
    'steel': {HINGE: 2, RING: 1.6, '30102000002': 5.2, '30104000002': 9},
    'stainless': {HINGE: 5, RING: 5.5, '30102000002': 23, '30104000002': 23},
    'common': {SEAL: 3.5, '30199000155': 5.8, '30199000156': 5.8},
}
existing = {(row.code, row.variant) for row in prices.search([('company_id', '=', design.company_id.id)])}
values = []
for variant, entries in by_variant.items():
    for code, price in entries.items():
        if (code, variant) in existing:
            continue
        name, unit, _ = ITEMS[code]
        scope = 'single' if code == RING else 'double' if code == SEAL else 'any'
        values.append(dict(company_id=design.company_id.id, code=code, name=name, unit=unit, variant=variant,
                           scope=scope, price_per_unit=price, basis='reference', source_note='AE 柜旧表规则复算'))

if ('AE-REF-EARTH-200', 'common') not in existing:
    values.append(dict(company_id=design.company_id.id, code='AE-REF-EARTH-200', name='接地编织带 200 mm',
                       price_per_unit=2.5, basis='reference', source_note='自选流程参考值'))
prices.create(values)
env.cr.commit()
print(f'AE 柜辅材参考价新增 {len(values)} 条。')
