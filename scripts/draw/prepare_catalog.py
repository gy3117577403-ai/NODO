"""Prepare private accessory previews with the pinned 0.57.3 CAD reader."""
import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from worker import ENGINE, EXCHANGE, HARDWARE, install_assets, publish, read


SAMPLE = {'width': 420, 'height': 340, 'depth': 235}
CATEGORIES = {'locks': '锁具与门控', 'hinges': '铰链与连接', 'bases': '底座与支撑',
              'protection': '防护与通风', 'mounting': '安装与固定', 'fasteners': '密封与紧固'}


def generate(work, source, *mode):
    output = work / 'preview.json'
    subprocess.run([sys.executable, str(ENGINE / 'src' / 'accessory_io.py'), str(source), str(output), *mode],
                   cwd=work, check=True, timeout=120)
    return read(output)


def builtin_preview(definition, work):
    if definition['kind'] == 'step':
        asset = 'library/' + definition['assetHash'] + '.step'
        install_assets(work, {'accessories': [{'definition': {**definition, 'assetPath': asset}}]})
        return generate(work, work / asset)['preview']
    model = {**definition, 'status': 'pending', 'holes': []}
    if model['kind'] == 'lock':
        model['holes'] = [dict(type='circle', u=0, v=0, diameter=model['diameter'])]
    params = dict(**SAMPLE, revision='V00', configuration={'kind': 'single', 'version': 2,
                  'seam': 5, 'templateId': 'AE-SINGLE-02'}, holes=[], materials={}, thickness={},
                  accessories=[dict(id='apreview', definition=model, face=model['face'], u=0, v=0,
                                    rotation=0, anchor='center', anchorV='center', side='outside',
                                    **{key: model[key] for key in ('thickness', 'height', 'overhang')})])
    source = work / 'preview-input.json'
    publish(source, params)
    return generate(work, source, '--accessory')


def store(meshes, model, mesh):
    key = f"{model['id']}-v{model['version']}"
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}-v[1-9][0-9]*', key):
        raise ValueError('附件型号预览编号不符合格式')
    if not mesh['parts'] or not all(part['valid'] and part['solids'] for part in mesh['parts']):
        raise ValueError(f"{model['code']} 缺少有效 STEP 实体预览")
    publish(meshes / (key + '.json'), {**mesh, 'model': model['name'], 'faces': [], 'parameters': {}})


def stage_pending(desktop, work, meshes):
    entries = []
    for item in read(desktop / 'index.json'):
        if item.get('archived') or item.get('kind') != 'step':
            continue
        digest = item['assetId']
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('京能附件原文件摘要格式无效')
        source = desktop / (digest + '.step')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError(f"{item['code']} STEP 与桌面库索引的摘要不同")
        model = {key: item[key] for key in ('id', 'code', 'name', 'version', 'kind', 'source', 'rules') if key in item}
        model.update(assetHash=digest, categoryName=CATEGORIES.get(item.get('category'), '其他附件'))
        store(meshes, model, generate(work, source)['preview'])
        entries.append(model)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-library', required=True, type=Path, help='京能桌面版附件库索引和 STEP 所在目录')
    args = parser.parse_args()
    catalog = EXCHANGE / 'catalog'
    meshes = catalog / 'meshes'
    meshes.mkdir(parents=True, exist_ok=True)
    builtins = read(HARDWARE.parent / 'library.json')
    with tempfile.TemporaryDirectory(prefix='nodo-catalog-') as temporary:
        work = Path(temporary)
        for code, definition in builtins.items():
            model = {**definition, 'code': code}
            store(meshes, model, builtin_preview(model, work))
        pending = stage_pending(args.desktop_library.resolve(), work, meshes)
    publish(catalog / 'pending.json', {'models': pending})
    print(f'附件模型预览已准备：{len(builtins)} 个内置型号，{len(pending)} 个待工程核对型号。')


if __name__ == '__main__':
    main()
