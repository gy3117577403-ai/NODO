"""Publish the original DWGs and their existing vector previews to NODO's private exchange."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
EXCHANGE = REPO / '.nodo-draw' / 'exchange'
STANDARDS = REPO / 'addons' / 'nodo_draw' / 'data' / 'reference_cabinets.json'


def read(path):
    return json.loads(path.read_text('utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_verified(source, target):
    if target.is_file():
        if digest(target) != digest(source):
            raise ValueError(f'原图目标与来源不同 {target.name}')
    else:
        shutil.copyfile(source, target)


def prepare(app):
    if read(app / 'package.json')['version'] != '0.57.3':
        raise ValueError('请使用已核对的京能 0.57.3 工程资源')
    engineering = app / 'engineering' / 'ae-cabinet'
    for kind, standard in read(STANDARDS).items():
        artifact = engineering / 'artifacts' / standard['artifact']
        parameters = read(artifact / 'parameters.json')
        if (parameters['configuration']['kind'] != kind or parameters['accessories'] or parameters['holes'] or
                any(parameters[key] != value for key, value in standard['dimensions'].items())):
            raise ValueError(f'{kind} 原图参数与柜型目录不一致')
        references = read(artifact / 'result.json')['sourceReferences']
        if len(references) != standard['sheet_count'] or references[0]['category'] != 'assembly':
            raise ValueError(f'{kind} 原图目录不完整')
        destination = EXCHANGE / 'reference' / kind
        destination.mkdir(parents=True, exist_ok=True)
        index = []
        for row in references:
            key, name = row['id'], row['originalName']
            if not re.fullmatch(r'basis_\d{2}', key) or Path(name).name != name or not name.endswith('.dwg'):
                raise ValueError('原图索引格式无效')
            source = engineering / 'source' / name
            original = artifact / 'source' / f'{key}.dwg'
            if digest(source) != row['sha256'] or digest(original) != row['sha256']:
                raise ValueError(f'原图摘要不一致 {name}')
            copy_verified(original, destination / f'{key}.dwg')
            copy_verified(artifact / 'preview' / f'{key}.svg', destination / f'{key}.svg')
            index.append(dict(key=key, name=row['name'], category=row['category'], filename=name, sha256=row['sha256']))
        if len({row['key'] for row in index}) != len(index):
            raise ValueError('原图编号重复')
        draft = destination / 'index.json.tmp'
        draft.write_text(json.dumps(index, ensure_ascii=False, indent=2), 'utf-8')
        draft.replace(destination / 'index.json')
        print(f'{standard["label"]} {len(index)} 张，原始 DWG 摘要已核对')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path, help='京能 0.57.3 安装目录中的 resources/app')
    prepare(parser.parse_args().app.resolve())
