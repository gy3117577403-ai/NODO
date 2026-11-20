"""Read back the mixed-gauge AE-304 browser delivery on the development fixture."""
import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from verify_ae303 import dwg_readback, verify_bom_rows
from verify_sample import bd, require, rows, step_leaves

EXPECTED = {
    'wrap': ('冷轧板', 1.6),
    'top': ('不锈钢板 · 304', 1.8),
    'bottom': ('冷轧板', 1.6),
    'door': ('冷轧板', 2),
    'mount': ('镀锌板', 2.5),
    'brace': ('冷轧板', 1.5),
}


def check_thickness(solid, face, thickness):
    def at_depth(depth):
        return tuple(origin + face['width'] * .35 * u + face['height'] * .43 * v - depth * normal
                     for origin, u, v, normal in zip(face['origin'], face['uAxis'], face['vAxis'], face['normal']))

    require(all(solid.is_inside(at_depth(depth)) for depth in (.02, thickness - .02))
            and not solid.is_inside(at_depth(thickness + .02)), face['name'] + '的 STEP 板厚不符')


def verify(delivery, run, temporary):
    request = json.loads((run.parent / 'request.json').read_bytes())
    require(request['source'] == 'AE-304' and request['source_version'] == '1' and request['quantity'] == 1,
            '仅核对 AE-304 混合板材样例')
    model_path = delivery / '整柜.step'
    bom_path = delivery / '零件清单.csv'
    with zipfile.ZipFile(delivery / '工程图包.zip') as archive:
        require(archive.testzip() is None, '工程图包 CRC 错误')
        require(model_path.read_bytes() == archive.read('model.step') and
                bom_path.read_bytes() == archive.read('零件清单.csv'), '单独下载件与图包属于不同版本')
        result = json.loads(archive.read('result.json'))
        parameters = result['parameters']
        require(parameters == json.loads(archive.read('parameters.json')) and
                parameters['revision'] == request['parameters']['revision'], '任务与下载版本不符')
        sheet = result['sheet']['parts']
        materials = result['materials']['parts']
        require(materials['top']['grade'] == '304' and materials['top']['condition'] == '2B'
                and materials['wrap']['finish'] == 'RAL7035', '牌号、来料状态或原图表面处理未保留')
        documents, cuts, _ = dwg_readback(archive, result['drawings'], run, temporary)
        for part, (material_name, gauge) in EXPECTED.items():
            spec = materials[part]
            label = ' · '.join(value for value in (spec['name'], spec.get('grade')) if value)
            require((label, sheet[part]) == (material_name, gauge), part+'工程参数不符')
            drawing = next(item for item in result['drawings'] if item['part'] == part and item['category'] == 'flat')
            require(drawing['thickness'] == gauge and drawing['material'] == spec, part+'展开材料或厚度不符')
            labels = {entity.plain_text().strip() for entity in documents[part].modelspace().query('TEXT MTEXT')}
            caption = f'{spec["name"]} {gauge:g} mm'
            require(drawing['materialCaption'] == caption and caption in labels, part+'实际展开图材料标注不符')

    model = bd.import_step(model_path)
    solids = {part.label: part for part in step_leaves(model)}
    require(model.is_valid and set(solids) == {part['id'] for part in result['parts']}, 'STEP 实体未与明细逐件对应')
    for face in result['faces']:
        if face['id'] in ('top', 'bottom', 'back', 'door', 'mount'):
            check_thickness(solids[face['part']], face, EXPECTED[face['part']][1])
    bom = rows(bom_path)[1:]
    pages = verify_bom_rows(bom, result['drawings'], documents)
    require(len(bom) == len(solids) and all(row[5:7] == ['1','1'] for row in bom), '清单台数或实体数量不符')
    for part, row in zip(result['parts'], bom):
        part_id = part['id']
        key = 'brace' if part_id.startswith('brace_') else part_id
        if key not in EXPECTED:
            continue
        require((row[3], float(row[4])) == EXPECTED[key], part_id+'清单材厚不符')
    return {'source': request['source'], 'revision': parameters['revision'], 'sheet_parts': EXPECTED,
            'step_sections': 5, 'step_solids': len(solids), 'dwg': len(documents), 'cut_dxf': len(cuts),
            'bom_pages': pages, 'engineering_status': result['engineeringStatus']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('delivery', type=Path)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nodo-sheet-readback-') as directory:
        print(json.dumps(verify(args.delivery, args.run, Path(directory)), ensure_ascii=False, indent=2))
