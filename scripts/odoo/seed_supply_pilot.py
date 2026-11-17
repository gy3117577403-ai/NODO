# Only run through scripts/nodo.ps1 seed-supply-pilot against nodo_dev.
import os

from odoo.fields import Command


if env.cr.dbname != 'nodo_dev' or not env.ref('nodo_supply.group_purchase_buyer', raise_if_not_found=False):
    raise RuntimeError('请先在 nodo_dev 安装 nodo_supply。')

roles = [
    ('assistant', '采购助理', 'nodo_supply.group_purchase_assistant'),
    ('engineer', '技术核对员', 'nodo_base.group_role_engineering'),
    ('buyer', '采购经办', 'nodo_supply.group_purchase_buyer'),
    ('manager', '采购经理', 'nodo_supply.group_purchase_manager'),
]
users = env['res.users'].with_context(no_reset_password=True)
created = []
existing = []
for key, name, group in roles:
    login = f'supply.{key}@nodo.test'
    if users.with_context(active_test=False).search_count([('login', '=', login)]):
        existing.append(login)
        continue
    users.create({
        'name': name,
        'login': login,
        'email': login,
        'lang': 'zh_CN',
        'tz': 'Asia/Shanghai',
        'password': os.environ[f'NODO_SUPPLY_{key.upper()}_PASSWORD'],
        'company_id': env.company.id,
        'company_ids': [Command.set(env.company.ids)],
        'group_ids': [Command.set([env.ref(group).id])],
    })
    created.append((key, login, name))

partners = env['res.partner']
if not partners.with_context(active_test=False).search_count([('ref', '=', 'NODO-SUPPLY-V042')]):
    partners.create({'name': '雾岬物资', 'ref': 'NODO-SUPPLY-V042', 'supplier_rank': 1})

products = env['product.product']
if not products.with_context(active_test=False).search_count([('default_code', '=', 'NODO-SUPPLY-042')]):
    products.create({
        'name': '配线标识加工',
        'default_code': 'NODO-SUPPLY-042',
        'type': 'service',
        'purchase_ok': True,
        'sale_ok': False,
    })

env.cr.commit()
for key, login, name in created:
    print('NODO_SUPPLY_USER_CREATED', key, login, name)
for login in existing:
    print('已存在，未改动：', login)
print('采购资料：雾岬物资、[NODO-SUPPLY-042] 配线标识加工。')
