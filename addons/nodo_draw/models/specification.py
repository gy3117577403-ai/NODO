"""The BOM is per cabinet. Model definitions and their installation rules are revisioned together."""
import copy
import json
import math
from pathlib import Path

from . import sheet_settings

DATA = Path(__file__).resolve().parents[1] / 'data'
LIBRARY = json.loads((DATA / 'library.json').read_text('utf-8'))
SAMPLES = json.loads((DATA / 'samples.json').read_text('utf-8'))
FACES = {'door': '门板', 'door_right': '右门板', 'top': '顶板', 'bottom': '底板',
         'back': '围板背面', 'left': '左侧板', 'right': '右侧板', 'mount': '安装板'}


def number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}须在 {low:g} 至 {high:g} 之间')
    return value


def count(value, label, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{label}须为 1 至 {maximum} 的整数')
    return value


def label(value, title, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f'{title}需要 1 至 {limit} 个可显示字符')
    return value.strip()


def intake(raw):
    if not isinstance(raw, dict):
        raise ValueError('请提供一份附件 BOM')
    rows = raw.get('lines')
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError('附件清单须为最多 200 行的列表')
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('附件行格式无效')
        code = label(row.get('code'), '附件编码')
        face = row.get('face', '')
        if face and face not in FACES:
            raise ValueError('附件安装面无效')
        lines.append(dict(code=code, name=label(row.get('name', code), '附件名称'),
                          quantity=count(row.get('quantity'), '每台用量', 10000), face=face))
    kind = raw.get('kind') or ''
    if kind not in ('', 'single', 'double'):
        raise ValueError('柜型须为单开门或双开门')
    dims = {k: number(raw[k], '箱体尺寸', 1, 10000) if raw.get(k) is not None else None
            for k in ('width', 'height', 'depth')}
    drawing = {}
    if 'drawing_number' in raw or 'drawing_revision' in raw:
        drawing = {k: label(raw.get(k), title) for k, title in
                   [('drawing_number', '总装图号'), ('drawing_revision', '图版')]}
    return dict(source=label(raw.get('source'), '来源明细编号'), title=label(raw.get('title'), '设计名称'), **drawing,
                source_version=label(raw.get('source_version', '1'), '来源版本', 30),
                quantity=count(raw.get('quantity'), '柜体台数', 10000), kind=kind, lines=lines, **dims)


def initial(bom):
    return {**{k: bom[k] for k in ('kind', 'width', 'height', 'depth')},
            'materials': {}, 'thickness': {},
            'holes': [], 'matches': {}, 'instances': []}


def edit(old, raw, lines, library):
    if not isinstance(raw, dict):
        raise ValueError('设计参数格式无效')
    new = sheet_settings.for_editor(old)
    kind = raw.get('kind')
    if kind not in ('single', 'double'):
        raise ValueError('请选择单开门或双开门')
    new['kind'] = kind
    for key, title in [('width', '柜宽'), ('height', '柜高'), ('depth', '柜深')]:
        new[key] = number(raw.get(key), title, 1, 10000)
    new.update(sheet_settings.edit(raw))
    matches = raw.get('matches', {})
    if not isinstance(matches, dict) or set(matches) - {str(i) for i in range(len(lines))}:
        raise ValueError('附件对应行无效')
    new['matches'] = {}
    for key, choice in matches.items():
        if not isinstance(choice, dict):
            raise ValueError('附件匹配格式无效')
        code, face = choice.get('code', ''), choice.get('face', '')
        if not isinstance(code, str) or not isinstance(face, str) or (code and code not in library) or (face and face not in FACES):
            raise ValueError('附件型号或安装面无效')
        new['matches'][key] = {'code': code, 'face': face}
    holes = raw.get('holes', [])
    if not isinstance(holes, list) or len(holes) > 300:
        raise ValueError('单柜自定义孔最多 300 个')
    new['holes'] = []
    seen = set()
    footprints = {}
    for h in holes:
        if not isinstance(h, dict):
            raise ValueError('孔记录无效')
        ident = label(h.get('id'), '孔号', 30)
        face, shape = h.get('face'), h.get('type')
        if ident in seen or not ident.startswith('H') or not ident[1:].isdigit():
            raise ValueError('自定义孔须有唯一的 H 编号')
        if face not in FACES or (face == 'door_right' and kind != 'double'):
            raise ValueError(f'{ident} 的板面与柜型不符')
        if shape not in ('circle', 'rectangle', 'slot'):
            raise ValueError('请选择圆孔、矩形孔或长圆孔')
        seen.add(ident)
        row = dict(id=ident, face=face, type=shape, anchor='left', anchorV='bottom')
        for axis in ('u', 'v'):
            row[axis] = number(h.get(axis), '距边尺寸', 0, 10000)
        size_fields = ('diameter',) if shape == 'circle' else ('width', 'height')
        for field in size_fields:
            row[field] = number(h.get(field), '孔尺寸', 2, 200 if shape == 'circle' else 250)
        footprint = (face, shape, row['u'], row['v'], *(row[field] for field in size_fields))
        if footprint in footprints:
            raise ValueError(f'{ident} 与 {footprints[footprint]} 位置、孔型和尺寸相同，请调整孔位。')
        footprints[footprint] = ident
        new['holes'].append(row)
    requested = raw.get('positions', {})
    existing = {a['id'] for a in old['instances']}
    if not isinstance(requested, dict) or set(requested) - existing:
        raise ValueError('装配实例无效')
    new['instances'] = []
    for item in old['instances']:
        row = match_row(new, lines, library, item['row'])
        if item['code'] != row['code'] or item['face'] != row['face'] or row['issue']:
            continue
        item = dict(item)
        position = requested.get(item['id'])
        if position is not None and library[item['code']]['kind'] not in ('base', 'canopy'):
            item.update(position_values(position))
        new['instances'].append(item)
    return new


def position_values(position):
    if not isinstance(position, dict):
        raise ValueError('附件位置格式无效')
    rotation = position.get('rotation', 0)
    if type(rotation) is not int or rotation not in (0, 90, 180, 270):
        raise ValueError('安装转角无效')
    return {axis: number(position.get(axis), '附件中心偏移', -10000, 10000) for axis in ('u', 'v')} | {'rotation': rotation}


def match_row(settings, lines, library, i):
    line = lines[i]
    choice = settings['matches'].get(str(i), {})
    code = choice.get('code') or line['code']
    if code not in library and not choice.get('code'):
        alias = code.strip().casefold()
        candidates = [key for key, model in library.items() if any(name.strip().casefold() == alias for name in model.get('aliases', []))]
        if len(candidates) > 1:
            return dict(code=code, face='', issue='有多个匹配型号，请手动选择')
        if candidates:
            code = candidates[0]
    model = library.get(code)
    face = choice.get('face') or line['face'] or (model['face'] if model else '')
    issue = ''
    if not model:
        issue = '待匹配型号'
    elif model.get('cabinetKinds') and settings['kind'] not in model['cabinetKinds']:
        issue = '所选柜型与附件安装规则不符'
    elif face not in model.get('faces', [model['face']]) or (face == 'door_right' and settings['kind'] != 'double'):
        issue = '安装面与柜型不符'
    else:
        rules = model.get('rules', {})
        low, high = rules.get('minThickness'), rules.get('maxThickness')
        if low is not None or high is not None:
            part = 'door' if face == 'door_right' else face if face in ('door', 'top', 'bottom', 'mount') else 'wrap'
            thickness = sheet_settings.panel_thickness(settings, part)
            if (low is not None and thickness < low) or (high is not None and thickness > high):
                issue = f'安装面板厚 {thickness:g} mm 不在型号适用范围'
    return dict(code=code, face=face, issue=issue)


def assemble(settings, lines, library, positions=None):
    positions = {} if positions is None else positions
    if not isinstance(positions, dict):
        raise ValueError('装配定位表格式无效')
    rows = [match_row(settings, lines, library, i) for i in range(len(lines))]
    totals = {}
    for i, row in enumerate(rows):
        totals[row['code']] = totals.get(row['code'], 0) + lines[i]['quantity']
    existing = {a['id']: a for a in settings['instances']}
    instances = []
    issues = []
    for i, row in enumerate(rows):
        code = row['code']
        issue = row['issue']
        if not issue and totals[code] > library[code]['maxQuantity']:
            issue = '每柜数量超出该型号规则'
        if not issue and sum(totals.values()) > 30:
            issue = '单柜装配容量为 30 件'
        if issue:
            issues.append(f'第 {i + 1} 行 {code} · {issue}')
            continue
        model = library[code]
        placement = model.get('placement', {})
        spacing = placement.get('spacing')
        fixed = model['kind'] not in ('base', 'canopy')
        for n in range(lines[i]['quantity']):
            ident = f'a{i+1}n{n+1}'
            current = existing.get(ident)
            supplied = positions.get(ident)
            if supplied is not None and fixed:
                location = position_values(supplied)
            elif current and current['code'] == code and current['face'] == row['face']:
                location = {key: current[key] for key in ('u', 'v', 'rotation')}
            elif lines[i]['quantity'] == 1 or spacing:
                location = {axis: placement.get(axis, 0) + n*(spacing or {}).get(axis, 0) for axis in ('u', 'v')}
                location['rotation'] = 0
            else:
                issues.append(f'第 {i + 1} 行 {code} · 第 {n + 1} 件缺少定位，请填写横向和纵向坐标')
                continue
            instances.append(dict(id=ident, row=i, code=code, face=row['face'], **location))
    if not issues:
        if set(positions) - {item['id'] for item in instances}:
            raise ValueError('装配定位包含不在当前匹配中的附件')
        settings['instances'] = instances
    return issues


def parameters(settings, library, revision):
    kind = settings['kind']
    p = {k: settings[k] for k in ('width', 'height', 'depth')}
    p.update(revision=f'V{revision:02}', configuration={'kind': kind, 'version': 2, 'seam': 5,
             'templateId': 'AE-' + kind.upper() + '-02'}, holes=copy.deepcopy(settings['holes']),
             **sheet_settings.for_design(settings),
             accessories=[])
    for item in settings['instances']:
        m = library[item['code']]
        definition = {k: copy.deepcopy(m[k]) for k in ('id', 'name', 'kind', 'version', 'source',
                      'mount', 'assetHash', 'size', 'bounds') if k in m}
        centers = m.get('holeCenters', [[0, 0]] if m['kind'] == 'lock' else [])
        holes = copy.deepcopy(m['holes']) if 'holes' in m else [
            dict(type='circle', u=u, v=v, diameter=m['diameter']) for u, v in centers
        ]
        placement = m.get('placement', {})
        opening = m.get('templateOpening')
        if (opening and opening['templateId'] == p['configuration']['templateId']
                and opening['face'] == item['face'] and item['u'] == placement['u']
                and item['v'] == placement['v']):
            # This square opening is already present in the native door solid and flat.
            # Retain its provenance. A relocated lock still needs its own new cutout.
            definition['templateOpening'] = copy.deepcopy(opening)
            holes = []
        definition.update(code=item['code'], status='pending', holes=holes,
                          rules={**m.get('rules', {}), 'faces': m.get('faces', [m['face']]), 'maxQuantity': m['maxQuantity']})
        if 'assetHash' in m:
            definition['assetPath'] = 'library/' + m['assetHash'] + '.step'
        p['accessories'].append({**{k: item[k] for k in ('id','face','u','v','rotation')},
            'anchor':placement.get('anchor','center'),'anchorV':placement.get('anchorV','center'),
            'side':'outside','definition':definition,
            **{k:m[k] for k in ('height','thickness','overhang')}})
    return p
