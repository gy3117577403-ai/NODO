"""Measure the same developed faces that the AE-202 cutting DXFs export."""
import json
import sys
from pathlib import Path


ENGINE_SRC = Path(__file__).resolve().parents[2] / '.nodo-draw/engineering/ae-cabinet/src'
PART_NAMES = {
    'wrap': '围板', 'top': '顶板', 'bottom': '底板', 'door': '左门板',
    'door_right': '右门板', 'mount': '安装板', 'brace': '门内加强件',
}
DENSITY = 7.85  # kg per square metre and millimetre of gauge


def write_flat_preview(flat, target):
    from cadgen import build123d as bd

    face = flat['face']
    bounds = face.bounding_box().size
    span = max(bounds.X, bounds.Y)
    drawing = bd.ExportSVG(margin=span * .035, line_weight=span / 580,
                           line_color=bd.Color('#245b50'), fill_color=bd.Color('#e0ece6'))
    drawing.add_shape(face)
    if flat['bends']:
        drawing.add_layer('BEND', line_color=bd.Color('#6e8b83'),
                          line_weight=span / 1050, line_type=bd.LineType.DASHED)
        for start, end in flat['bends']:
            if start != end:
                drawing.add_shape(bd.Edge.make_line((*start, 0), (*end, 0)), layer='BEND')
    drawing.write(target)


def build_usage(mesh, destination):
    from cadgen import build123d as bd
    from flats import prepared_flat
    from materials import label as material_label, resolve as material_for
    from reference_models import DUAL_FLATS

    parameters = mesh['parameters']
    if parameters['configuration'].get('templateId') != 'AE-DOUBLE-02':
        raise ValueError('当前三维模型与双门柜展开模板不一致')
    members = {key: [] for key in PART_NAMES}
    for part in mesh['parts']:
        key = 'brace' if part['id'].startswith('brace_') else part['id']
        if key in members:
            members[key].append(part)

    rows = []
    for key, parts in members.items():
        if not parts:
            raise ValueError(f'{PART_NAMES[key]} 缺少对应三维零件')
        first = parts[0]
        if any((p['code'], p['thickness']) != (first['code'], first['thickness']) for p in parts):
            raise ValueError(f'{PART_NAMES[key]} 同一展开图的零件规格不一致')
        flat = prepared_flat(key, parameters)
        # Inner wires remain visible in the drawing and consume material in the blank.
        area = bd.Face(flat['face'].outer_wire()).area / 1_000_000
        quantity = len(parts)
        thickness = first['thickness']
        row = dict(key=key, name=PART_NAMES[key], code=first['code'], material=material_label(material_for(parameters, key)),
                   thickness=thickness, quantity=quantity, area=area,
                   weight=area * thickness * DENSITY * quantity, needs_review=key not in DUAL_FLATS,
                   instances=[{'id': p['id'], 'name': p['name']} for p in parts])
        write_flat_preview(flat, destination / f'{key}.svg')
        rows.append(row)
    return dict(rows=rows, density=DENSITY, pieces=sum(r['quantity'] for r in rows),
                area=sum(r['area'] * r['quantity'] for r in rows), weight=sum(r['weight'] for r in rows))


if __name__ == '__main__':
    sys.path.insert(0, str(ENGINE_SRC))
    mesh_path, destination = map(Path, sys.argv[1:])
    usage = build_usage(json.loads(mesh_path.read_text('utf-8')), destination)
    (destination / 'usage.json').write_text(json.dumps(usage, ensure_ascii=False, allow_nan=False), 'utf-8')
