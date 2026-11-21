"""Prepare the temporary browser acceptance database, never the normal workspaces."""
import os
import re

from odoo import Command
from odoo.addons.nodo_draw.models import specification as spec, workbench
from odoo.tests.common import new_test_user


if not re.fullmatch(r'nodo_test_[0-9]{14}', env.cr.dbname):
    raise RuntimeError('浏览器验收只能写入一次性测试库。')

password = os.environ['NODO_DRAW_BROWSER_PASSWORD']
company = env.company
company.name = 'NODO'
catalog = env['nodo.draw.accessory']
catalog._seed_catalog(include_local=True)
designs = env['nodo.draw.design']
for sample in spec.SAMPLES[1:]:
    designs.handoff_bom(sample)

backups = sorted(workbench.EXCHANGE.glob('dev-cabinets-backup-*.json'))
if not backups:
    raise RuntimeError('缺少开发柜体归档索引。')
index = workbench.read_json(backups[-1])
source = next(row for row in index['nodo_draw_design'] if row['source'] == 'AE-303' and row['source_version'] == '2')
batch = next(row for row in index['nodo_draw_job'] if row['design_id'] == source['id'] and row['version'] == 2
             and row['operation'] == 'build' and row['final_state'] == 'done')
if not re.fullmatch(r'[a-f0-9]{32}', batch['token']):
    raise RuntimeError('原始归档编号无效。')
status = workbench.read_json(workbench.EXCHANGE / batch['token'] / 'status.json')
if status.get('state') != 'done' or not {'mesh', 'bundle'}.issubset(status.get('files', {})):
    raise RuntimeError('AE-303 V02 原始归档不完整。')
archive_company = env['res.company'].create({'name': 'NODO 工程归档'})
archive = designs.create({**{key: source[key] for key in ('name','source','source_version','bom','library','settings','edit_number')},
                          'company_id': archive_company.id})
env['nodo.draw.job'].create({**{key: batch[key] for key in ('token','payload','version','edit_number','operation','final_state')},
                            'design_id': archive.id, 'company_id': archive_company.id})

for login, name, owner in [('draw.engineer@nodo.test', '技术员', company), ('draw.archive@nodo.test', '技术档案员', archive_company)]:
    new_test_user(env, login=login, name=name, password=password, groups='nodo_base.group_role_engineering',
                  context={'no_reset_password': True}, lang='zh_CN', company_id=owner.id, company_ids=[Command.set(owner.ids)])
env.cr.commit()
print('本机浏览器验收库已准备 AE-303 交接版 2、AE-202 双门及只读 V02 档案引用。')
