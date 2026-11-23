"""Verify the stock AE-202 blank with and without a right-door cutout."""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

from sheet_usage import ENGINE_SRC, build_usage


def verify(mesh_path):
    sys.path.insert(0, str(ENGINE_SRC))
    from flats import prepared_flat

    mesh = json.loads(mesh_path.read_text(encoding='utf-8'))
    parameters = mesh['parameters']
    with tempfile.TemporaryDirectory(prefix='nodo-sheet-usage-') as temporary:
        target = Path(temporary)
        before = build_usage(mesh, target)
        assert len(before['rows']) == 7 and before['pieces'] == 10
        assert round(before['area'], 6) == 3.226993 and round(before['weight'], 3) == 45.886
        assert {r['key'] for r in before['rows'] if r['needs_review']} == {'door', 'door_right', 'brace'}
        originals = {r['key']: r for r in before['rows'] if r['area_source']['method'] == 'original'}
        assert set(originals) == {'wrap', 'top', 'bottom', 'mount'}
        for key, mm2 in [('top', 311182.5913), ('bottom', 311181.8516), ('mount', 627239.3803), ('wrap', 1135280.5699)]:
            assert abs(originals[key]['area'] * 1e6 - mm2) < .001
            assert len(originals[key]['area_source']['hash']) == 64
        assert .0108 < originals['wrap']['area_source']['max_gap_mm'] < .011
        for row in before['rows']:
            assert ElementTree.parse(target / (row['key'] + '.svg')).getroot().tag.endswith('}svg')
        right_door = target / 'door_right.svg'
        original_svg = right_door.read_bytes()
        original_net = prepared_flat('door_right', parameters)['face'].area

        parameters.setdefault('holes', []).append(dict(
            id='H_USAGE', face='door_right', type='circle', u=120, v=185,
            diameter=18, anchor='start', anchorV='start',
        ))
        after = build_usage(mesh, target)
        new_net = prepared_flat('door_right', parameters)['face'].area
        assert math.isclose(original_net - new_net, math.pi * 9**2, abs_tol=1e-5)
        assert original_svg != right_door.read_bytes()
        assert math.isclose(before['area'], after['area'], rel_tol=0, abs_tol=1e-10)
        assert math.isclose(before['weight'], after['weight'], rel_tol=0, abs_tol=1e-8)
        next(part for part in mesh['parts'] if part['id'] == 'wrap')['code'] = '其他零件图号'
        try:
            build_usage(mesh, target)
        except ValueError as exc:
            assert '零件图号' in str(exc)
        else:
            raise AssertionError('同一尺寸下不同的零件图号不能套用原图')
        return dict(kinds=len(before['rows']), pieces=before['pieces'], weight_kg=before['weight'],
                    blank_area_m2=before['area'], new_cutout_mm2=original_net-new_net)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mesh', type=Path, help='标准 AE-202 的三维预览 mesh.json')
    print(json.dumps(verify(parser.parse_args().mesh)))
