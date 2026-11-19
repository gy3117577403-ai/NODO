"""Run the private 0.57.3 engine with accessory-aware assembly drawing checks."""
import copy
import json
import runpy
import sys
from itertools import combinations, product
from pathlib import Path


ENGINE = Path(__file__).resolve().parents[2] / '.nodo-draw' / 'engineering' / 'ae-cabinet'


def check_assembly(source, returned, expected, work, original_verify):
    from assembly_template import project_point
    from cadgen import build123d as bd

    # The old six-view verifier assumes that cabinet and assembly have the same
    # outline. External accessories can enlarge it without changing cabinet W/H/D.
    # Measure the actual exported STEP independently of the drawing and mesh.
    solid = bd.import_step(work / 'model.step')
    bounds = solid.bounding_box()
    corners = list(product(*zip(bounds.min, bounds.max)))
    physical = copy.deepcopy(expected)
    layout = physical['assemblyLayout']
    page_left, page_bottom, page_right, page_top = layout['content']
    boxes = []
    for view in layout['views']:
        points = [project_point(view, corner) for corner in corners]
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        bottom, top = min(p[1] for p in points), max(p[1] for p in points)
        if left < page_left or bottom < page_bottom or right > page_right or top > page_top:
            raise ValueError(f"含附件的{view['name']}超出原图可用区域")
        boxes.append((left, bottom, right, top))
        view['origin'] = [left, bottom]
        view['size'] = [right-left, top-bottom]
    for a, b in combinations(boxes, 2):
        if min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]):
            raise ValueError('含附件的总装视图重叠')
    proof = original_verify(source, returned, physical)
    proof['assemblyEnvelopeSource'] = 'model.step'
    proof['assemblyBounds'] = [list(bounds.min), list(bounds.max)]
    return proof


def main():
    sys.path.insert(0, str(ENGINE))
    sys.path.insert(0, str(ENGINE / 'src'))
    from cadgen import build123d  # Initialize the CAD kernel before binding its verifier.
    import drawings
    import incremental

    work = Path(sys.argv[2]).resolve()
    parameters = json.loads(Path(sys.argv[1]).read_text('utf-8'))
    if parameters.get('accessories'):
        class CabinetComponents(incremental.Reuse):
            def prepare_components(self, parameters, root, run_model):
                super().prepare_components(parameters, root, run_model)
                models = {a['id']: a['definition'] for a in parameters['accessories']}
                names = {'front':'前板','back':'后板','left':'左侧板','right':'右侧板',
                         'post1':'支撑柱一','post2':'支撑柱二','post3':'支撑柱三','post4':'支撑柱四'}
                for ident, record in self.records.items():
                    meta = record['metadata']
                    model = models.get(meta.get('accessoryId'))
                    if model is None:
                        continue
                    suffix = ident.rsplit('_', 1)[-1]
                    if suffix == 'model':
                        meta['name'] = model['name']
                    elif suffix == 'plate':
                        plate = '罩板' if model['kind'] == 'canopy' else '安装板'
                        meta['name'] = model['name'] + ' · ' + plate
                    elif suffix in names:
                        meta['name'] = model['name'] + ' · ' + names[suffix]
        incremental.Reuse = CabinetComponents
        original_verify = drawings.verify_roundtrip
        def verify(source, returned, expected):
            if 'assemblyLayout' in expected:
                return check_assembly(source, returned, expected, work, original_verify)
            return original_verify(source, returned, expected)
        drawings.verify_roundtrip = verify
    runpy.run_path(str(ENGINE / 'build.py'), run_name='__main__')


if __name__ == '__main__':
    main()
