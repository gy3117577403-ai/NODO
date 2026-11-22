"""Single-cabinet selection rules from Jingneng sales c3c1209."""

import math
import re
import unicodedata
from collections import Counter
from hashlib import sha256
from json import dumps

from odoo.exceptions import ValidationError

from .quote_price import DOORS, allowed_doors, checked_number


SELECTION_DEFAULTS = {
    'product_series': '', 'width_mm': 0, 'width_expression': '', 'depth_mm': 0, 'height_mm': 0,
    'quantity': 1, 'material': 'SECC', 'thickness_mm': 1.5, 'base_height_mm': 0,
    'coating_type': 'orange', 'display_color': 'RAL7035 浅灰', 'door_type': '',
    'cabinet_configuration': {}, 'accessory_selection_data': {},
}
DOOR_KEYS = {value[0]: key for key, value in DOORS.items()}
TEXT_LIMIT = 120_000


def number(value, label):
    try:
        value = float(0 if value in (None, '') else value)
    except (TypeError, ValueError, OverflowError):
        value = -1
    if not math.isfinite(value) or value < 0:
        raise ValidationError(f'{label}须为有效的非负数。')
    return value


def cabinet_values(values):
    values = {key: values.get(key, default) for key, default in SELECTION_DEFAULTS.items()}
    for key, label in (
        ('width_mm', '宽度'), ('depth_mm', '深度'), ('height_mm', '高度'),
        ('thickness_mm', '料厚'), ('base_height_mm', '底座高度'), ('quantity', '数量'),
    ):
        values[key] = number(values[key], label)
    if values['quantity'] < 1 or not values['quantity'].is_integer():
        raise ValidationError('单柜按台填写，数量须为正整数。')
    width = values['width_mm']
    expression = str(values['width_expression'] or (f'{width:g}' if width else '')).strip()
    if expression:
        if len(expression) > 32 or not re.fullmatch(r'\d+(?:\.\d+)?', expression):
            raise ValidationError('请填写一个单柜宽度，单位为毫米。')
        width = number(expression, '宽度')
        if not width:
            raise ValidationError('单柜宽度须大于零。')
    configuration = values['cabinet_configuration'] or {}
    previous = configuration.get('cabinets', []) if isinstance(configuration, dict) else None
    if not isinstance(previous, list) or len(previous) > 1 or any(not isinstance(row, dict) for row in previous):
        raise ValidationError('当前报价使用单柜配置，请重新核对门型和宽度。')
    previous = previous[0] if previous else {}
    doors = allowed_doors(values['product_series'])
    selected = DOOR_KEYS.get(previous.get('door_type')) if previous.get('door_manual') else None
    if selected and selected not in doors:
        raise ValidationError('当前门型不适用于此柜体系列。')
    key = selected or (doors[1] if width > 800 and len(doors) > 1 else doors[0])
    door, front, rear, single, double = DOORS[key]
    cabinet = {
        'index': 0, 'width_mm': width, 'door_type': door, 'door_manual': bool(selected),
        'door_position': {'front': front, 'rear': rear},
        'single_door_count': single, 'double_door_count': double,
    }
    basis = [values[key] for key in ('product_series', 'depth_mm', 'height_mm', 'material', 'thickness_mm', 'coating_type')]
    signature = sha256(dumps([*basis, width, door], ensure_ascii=False).encode()).hexdigest()
    values.update(
        width_mm=width, width_expression=f'{width:g}' if width else '', door_type=door if width else '',
        cabinet_configuration={'version': 1, 'cabinets': [cabinet] if width else [], 'signature': signature},
    )
    return values


def chinese_characters(value):
    return re.findall(r'[\u3400-\u9fff]', unicodedata.normalize('NFKC', str(value or '')))


def accessory_overlap(name, text_counts):
    """Original rule: count each name character, and require at least 60% coverage."""
    characters = chinese_characters(name)
    common = Counter(characters) & text_counts
    count = sum(common.values())
    if not characters or count * 100 < len(characters) * 60:
        return None
    evidence = []
    for char in characters:
        if common[char]:
            evidence.append(char)
            common[char] -= 1
    return {
        'text': ''.join(evidence), 'matched_count': count, 'name_count': len(characters),
        'rate': round(count * 100 / len(characters), 1),
    }


def drawing_part_numbers(text):
    return frozenset(re.findall(r'[A-Z0-9][A-Z0-9_.-]*', unicodedata.normalize('NFKC', text).upper()))


def accessory_values(data, catalog, candidate_id, signature, *, require_quantity=False):
    data = data or {}
    if not isinstance(data, dict):
        raise ValidationError('附件选配数据无效。')
    choices, manual, rows = (data.get(key, default) for key, default in (
        ('choices', {}), ('manual_names', []), ('allocations', []),
    ))
    if not isinstance(choices, dict) or not isinstance(manual, list) or not isinstance(rows, list) or len(rows) > 100:
        raise ValidationError('附件选配数据无效，请重新选择。')
    if (len(choices) > 100 or len(manual) > 100 or any(not isinstance(name, str) for name in manual)
            or any(type(selected) is not bool for selected in choices.values())
            or any(not isinstance(row, dict) or not isinstance(row.get('name'), str) for row in rows)):
        raise ValidationError('附件选配数据无效，请重新选择。')
    names = dict.fromkeys([*choices, *manual, *(row['name'] for row in rows)])
    if len(names) > 100 or set(names) - set(catalog):
        raise ValidationError('有附件不在当前公司附件目录中，请核对选配。')
    prior = {row['name']: row for row in rows}
    allocations = []
    for name in names:
        row = prior.get(name, {})
        quantity = row.get('quantity', None if require_quantity else 1)
        if quantity is not None:
            quantity = number(quantity, '附件每台用量')
            if not quantity:
                raise ValidationError('附件每台用量须大于零。')
        dimensions = row.get('manual_inputs', {}) or {}
        if not isinstance(dimensions, dict) or len(dimensions) > 20 or any(
            not isinstance(key, str) or not key.strip() or len(key) > 60 or not checked_number(value) or value <= 0
            for key, value in dimensions.items()
        ):
            raise ValidationError('附件实测尺寸须以毫米填写正数。')
        selected = choices.get(name, row.get('selected', True))
        allocations.append({
            'name': name, 'scope': 'cabinet', 'cabinet_index': 0,
            'selected': bool(selected), 'quantity': quantity, 'manual_inputs': dimensions,
            'model_code': str(row.get('model_code') or '').strip()[:100],
        })
    return {
        'version': 1, 'candidate_id': candidate_id, 'manual_names': list(dict.fromkeys(manual)),
        'choices': {row['name']: row['selected'] for row in allocations},
        'allocations': allocations, 'configured_signature': signature,
    }
