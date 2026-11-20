"""Sheet stock follows the pinned AE material and thickness catalogs."""
import copy
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
MATERIALS = json.loads((DATA / 'materials.json').read_text('utf-8'))
SHEETS = json.loads((DATA / 'sheet-rules.json').read_text('utf-8'))
CATALOG = {'materials': MATERIALS, 'sheets': SHEETS}
GROUP_PARTS = {'body': 'wrap', 'door': 'door', 'mount': 'mount'}
DETAILS = ('grade', 'condition', 'finish', 'note')
LEGACY_FIELDS = {*GROUP_PARTS, 'material'}


def for_design(settings):
    materials = settings.get('materials')
    if materials is None:
        materials = {group: {'category': settings['material']} for group in GROUP_PARTS}
    thickness = settings.get('thickness')
    if thickness is None:
        thickness = {group: settings[group] for group in GROUP_PARTS}
    return {'materials': copy.deepcopy(materials), 'thickness': copy.deepcopy(thickness)}


def for_editor(settings):
    return {**{key: value for key, value in settings.items() if key not in LEGACY_FIELDS},
            **for_design(settings)}


def _entries(value, keys, message):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(message)
    return value


def _text(value, message):
    if not isinstance(value, str) or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError(message)


def _validate_materials(materials):
    _entries(materials, {*GROUP_PARTS, 'parts', 'finishes'}, '材料参数格式无效')
    parts = _entries(materials.get('parts', {}), MATERIALS['parts'], '未知板件材料')
    finishes = _entries(materials.get('finishes', {}), MATERIALS['parts'], '未知板件表面处理')
    for finish in finishes.values():
        _text(finish, '表面处理须为 120 字以内单行文字')
    for choice in [*(materials[group] for group in GROUP_PARTS if group in materials), *parts.values()]:
        _entries(choice, {'category', *DETAILS}, '材料详情格式无效')
        category = choice.get('category')
        if not isinstance(category, str) or category not in MATERIALS['categories']:
            raise ValueError('请选择有效的材料类别')
        for name in DETAILS:
            if name in choice:
                _text(choice[name], '材料详情须为 120 字以内单行文字')


def _validate_gauge(value, part):
    rule = SHEETS['parts'][part]
    minimum, maximum = rule['min'], rule['max']
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise ValueError(f'{rule["name"]}板厚须在 {minimum:g} 至 {maximum:g} mm 之间')


def _validate_thickness(thickness):
    _entries(thickness, {*GROUP_PARTS, 'parts'}, '板厚参数格式无效')
    parts = _entries(thickness.get('parts', {}), SHEETS['parts'], '未知板件厚度')
    for group, part in GROUP_PARTS.items():
        if group in thickness:
            _validate_gauge(thickness[group], part)
    for part, value in parts.items():
        _validate_gauge(value, part)


def edit(raw):
    if 'materials' in raw or 'thickness' in raw:
        materials, thickness = raw.get('materials'), raw.get('thickness')
    else:
        materials = {group: {'category': raw.get('material')} for group in GROUP_PARTS}
        thickness = {group: raw.get(group) for group in GROUP_PARTS}
    _validate_materials(materials)
    _validate_thickness(thickness)
    return {'materials': copy.deepcopy(materials), 'thickness': copy.deepcopy(thickness)}
