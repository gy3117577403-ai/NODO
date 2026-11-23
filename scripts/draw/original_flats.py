"""Measure the millimetre cutting contour of a pinned native AE flat."""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / 'addons/nodo_draw/data'
ENGINE = REPO / '.nodo-draw/engineering/ae-cabinet'
PROFILES = json.loads((DATA / 'sheet_sources.json').read_text('utf-8'))
STANDARDS = json.loads((DATA / 'reference_cabinets.json').read_text('utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_pack(kind):
    pack = PROFILES[kind]
    folder = REPO / '.nodo-draw/exchange/reference' / kind
    index = json.loads((folder / 'index.json').read_text('utf-8'))
    entries = sorted((r['filename'], r['sha256']) for r in index)
    identity = json.dumps(entries, ensure_ascii=False, separators=(',', ':')).encode()
    if hashlib.sha256(identity).hexdigest() != pack['revision']:
        raise ValueError('基础图包的文件版本已变化，请核对原图。')
    flat_pages = {r['key']: (r['filename'], r['sha256']) for r in index if r['category'] == 'flat'}
    for source in pack['flats'].values():
        if flat_pages.get(source['reference']) != (source['file'], source['dwg']):
            raise ValueError('展开原图页、图号或文件版本不一致：' + source['file'])
    for entry in index:
        if digest(ENGINE / 'source' / entry['filename']) != entry['sha256']:
            raise ValueError('模型来源与登记图包不同：' + entry['filename'])
        if entry['category'] == 'flat' and digest(folder / (entry['key'] + '.dwg')) != entry['sha256']:
            raise ValueError('工作台展开原图版本不符：' + entry['filename'])
    return pack


def original_area(key, entry, kind):
    from cadgen import build123d as bd
    from geometry import document, source_edges

    stem = Path(entry['file']).stem
    dxf = ENGINE / 'converted' / (stem + '.dxf')
    if digest(dxf) != entry['dxf']:
        raise ValueError(f'{stem} 的矢量转换件与登记原图版本不符')
    doc = document(stem)
    if doc.units != 4:
        raise ValueError(f'{stem} 未确认以毫米绘制')
    # The two pinned wrap DWGs repeat a corner and include four construction
    # segments on layer 0. The single mount repeats part of its upper edge.
    skip = set()
    if key == 'wrap':
        skip = {format(h, 'X') for h in [*range(0x13A, 0x141), *range(0x149, 0x14D)]}
    elif kind == 'single' and key == 'mount':
        skip = {'135'}
    handles = [e.dxf.handle for e in doc.modelspace()
        if e.dxf.layer in ('0', '1轮廓实线层_1', '粗实线层') and e.dxf.handle not in skip
        and e.dxftype() in ('LINE', 'ARC', 'SPLINE', 'LWPOLYLINE')]
    max_gap = 0
    edges = []
    if key == 'wrap':
        # Seven segments form one continuous corner stored slightly above its
        # two adjoining edges. Register that corner rigidly to its source datum.
        start = 0x19C if kind == 'double' else 0x177
        corner = [format(h, 'X') for h in range(start, start + 7)]
        end = doc.entitydb[corner[-1]]
        dy = doc.entitydb['139'].dxf.end.y - min(end.dxf.start.y, end.dxf.end.y)
        max_gap = abs(dy)
        if max_gap > .02:
            raise ValueError(f'{stem} 端点偏差超出已核对的图版范围')
        edges.extend(source_edges(doc, corner, lambda x, y: (x, y+dy, 0)))
        handles = [h for h in handles if h not in corner]
    edges.extend(source_edges(doc, handles, lambda x, y: (x, y, 0)))
    wires = bd.Wire.combine(edges, tol=.00002)
    if not wires or any(not w.is_closed for w in wires):
        raise ValueError(f'{stem} 没有唯一可核对的闭合外轮廓')
    outlines = sorted((bd.Face(w) for w in wires), key=lambda f: f.area, reverse=True)
    outer = outlines[0]
    if not outer.is_valid or any(not outer.is_inside(f.outer_wire().position_at(.5)) for f in outlines[1:]):
        raise ValueError(f'{stem} 的切割轮廓无效或含多个独立板件')
    return outer.area / 1_000_000, max_gap
