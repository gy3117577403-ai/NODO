from odoo.addons.nodo_draw.models.specification import SAMPLES

if env.cr.dbname != 'nodo_dev':
    raise RuntimeError('柜体样例只能写入本地开发库')
for bom in SAMPLES:
    env['nodo.draw.design'].handoff_bom(bom)
env.cr.commit()
print('技术工作台两份附件 BOM 已就绪。')
