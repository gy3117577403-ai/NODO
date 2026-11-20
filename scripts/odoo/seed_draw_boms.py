from odoo.addons.nodo_draw.models.standard_drawings import STANDARDS

if env.cr.dbname != 'nodo_dev':
    raise RuntimeError('基础柜只能写入本地开发库')

base_cabinets = (('AE-101', 'single', '单开门基础柜'), ('AE-202', 'double', '双开门基础柜'))
for source, kind, title in base_cabinets:
    env['nodo.draw.design'].handoff_bom({
        'source': source, 'kind': kind, 'title': title, 'quantity': 1, 'lines': [],
        **STANDARDS[kind]['dimensions'],
    })
env.cr.commit()
print(f'技术工作台 {len(base_cabinets)} 个基础柜已就绪。')
