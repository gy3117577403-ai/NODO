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
        return dict(kinds=len(before['rows']), pieces=before['pieces'], weight_kg=before['weight'],
                    blank_area_m2=before['area'], new_cutout_mm2=original_net-new_net)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mesh', type=Path, help='标准 AE-202 的三维预览 mesh.json')
    print(json.dumps(verify(parser.parse_args().mesh)))
