if env.cr.dbname != 'nodo_dev':
    raise RuntimeError('本机待核对型号只能登记到开发库。')

catalog = env['nodo.draw.accessory']
catalog._seed_catalog(include_local=True)
cards = catalog.list_accessory_models()
if not all(card['mesh'] for card in cards):
    raise RuntimeError('附件型号预览文件尚未准备完整。')
env.cr.commit()
print(f'附件库已就绪：{len(cards)} 个型号版本，{sum(card["state"] == "pending" for card in cards)} 个待工程核对。')
