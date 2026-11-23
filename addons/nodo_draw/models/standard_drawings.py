"""The raw reference sheets describe only the two native cabinet standards."""
import json

from .sheet_settings import DATA, MATERIALS, SHEETS


STANDARDS = json.loads((DATA / 'reference_cabinets.json').read_text('utf-8'))
SHEET_PACKS = json.loads((DATA / 'sheet_sources.json').read_text('utf-8'))


def sheet_profile(bom, kind):
    pack = SHEET_PACKS.get(kind)
    if not pack:
        return {}
    number = bom.get('drawing_number')
    revision = bom.get('drawing_revision')
    if (number or revision) and (number, revision) != (pack['number'], pack['revision']):
        return {}
    return {k: pack[k] for k in ('number', 'revision', 'template')}


def catalog(exchange):
    result = {}
    for kind, standard in STANDARDS.items():
        path = exchange / 'reference' / kind / 'index.json'
        sheets = json.loads(path.read_text('utf-8')) if path.is_file() else []
        result[kind] = dict(kind=kind, label=standard['label'], dimensions=standard['dimensions'], sheets=sheets)
    return result


def matches(parameters):
    standard = STANDARDS[parameters['configuration']['kind']]
    if any(parameters[key] != size for key, size in standard['dimensions'].items()):
        return False
    if parameters['holes'] or parameters['accessories']:
        return False
    gauges, materials = parameters['thickness'], parameters['materials']
    for part, rule in SHEETS['parts'].items():
        gauge = gauges.get('parts', {}).get(part, gauges.get(rule['group'], rule['default']))
        if gauge != rule['default']:
            return False
        group = MATERIALS['parts'][part]
        default_finish = MATERIALS['sourceFinish'].get(part, '')
        original = {'category': MATERIALS['groups'][group], 'finish': default_finish}
        stock = materials.get('parts', {}).get(part, materials.get(group, original))
        finish = materials.get('finishes', {}).get(part, stock.get('finish', ''))
        if stock['category'] != original['category'] or finish != default_finish:
            return False
        if any(stock.get(field) for field in ('grade', 'condition', 'note')):
            return False
    return True
