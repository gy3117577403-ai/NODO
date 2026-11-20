"""Read back the four files downloaded from the AE-306 cabinet's drawing version."""
import argparse
import json
import os
import subprocess
import tempfile
from collections import Counter
from itertools import pairwise
from pathlib import Path

import ezdxf
from cadgen import build123d as bd
from cadgen.drawing_checks import validate_dxf_file

from verify_sample import near, require, rows, signature, step_leaves


def verify(folder):
    evidence = json.loads((folder / '出图浏览器.json').read_text('utf-8'))
    require(evidence['source'] == 'AE-306', '验收文件不属于双门开孔样件')
    uv, size = (135.25, 155.75), (24, 14)
    xy, world = (148.07, 167.35), (882.25, 0, 158.75)
    coordinates = rows(folder / '孔位表.csv')[1:]
    require(len(coordinates) == 1, '孔位表应只有一个新增孔')
    hole = coordinates[0]
    require(hole[:4] == ['H1', '', 'door_right', '24×14'], '孔号、板面或规格不同')
    require(near(tuple(map(float, hole[4:8])), (*uv, *xy)), 'U/V 或展开坐标有偏差')
    require(near(tuple(map(float, hole[12:15])), world), '右门基准计算的实体坐标有偏差')

    model = bd.import_step(folder / '整柜.step')
    solids = {part.label:part for part in step_leaves(model)}
    require(model.is_valid and {'door', 'door_right'} <= solids.keys(), 'STEP 缺少有效的独立门板')
    right, left = solids['door_right'], solids['door']
    a, b = (value / 2 for value in size)
    inner = [(0,0),(a-.25,0),(-a+.25,0),(0,b-.25),(0,-b+.25)]
    outer = [(a+.25,0),(-a-.25,0),(0,b+.25),(0,-b-.25)]
    for depth in (.3, 1, 1.7):
        def right_has_material(du, dv):
            return right.is_inside((world[0]-du, depth, world[2]+dv))
        require(not any(right_has_material(*point) for point in inner), '右门 STEP 孔未完整贯穿')
        require(all(right_has_material(*point) for point in outer), '右门 STEP 切除超出孔尺寸')
        require(left.is_inside((2.5+uv[0], depth, world[2])), '左门被同时切孔')

    cutfile = folder / '右门切割.dxf'
    cut = ezdxf.readfile(cutfile)
    require(cut.units == 4 and all(entity.dxf.layer == 'CUT' for entity in cut.modelspace()), '切割 DXF 单位或图层不符')
    require(not validate_dxf_file(str(cutfile)), '切割 DXF 有开环或重边')
    lines = [(tuple(e.dxf.start)[:2],tuple(e.dxf.end)[:2]) for e in cut.modelspace().query('LINE')]
    x, y = xy
    corners = [(x-a,y-b),(x+a,y-b),(x+a,y+b),(x-a,y+b),(x-a,y-b)]
    for p,q in pairwise(corners):
        count = sum((near(p,s) and near(q,e)) or (near(p,e) and near(q,s)) for s,e in lines)
        require(count == 1, '新增矩形在切割 DXF 中缺边或重复')

    oda = Path(os.environ.get('AE_ODA_CONVERTER', r'C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe'))
    dwg = folder / '右门展开.dwg'
    with dwg.open('rb') as stream:
        require(stream.read(6) == b'AC1032', '右门展开文件缺少有效 DWG 文件头')
    with tempfile.TemporaryDirectory(prefix='nodo-drill-readback-') as temporary:
        back = Path(temporary)
        subprocess.run([str(oda),str(folder),str(back),'ACAD2018','DXF','0','1',dwg.name],
                       check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        converted = ezdxf.readfile(back / dwg.with_suffix('.dxf').name)
        require(Counter(map(signature,cut.modelspace())) ==
                Counter(signature(e) for e in converted.modelspace() if e.dxf.layer == 'CUT'),
                '展开 DWG 的实际切割层与独立 DXF 不一致')
    return dict(source=evidence['source'], revision=evidence['revision'], job=evidence['job'], face='door_right',
                hole='H1', center_uv=uv, flat_xy=xy, world_xyz=world, size_mm=size,
                step_depth_samples=3, cut_rectangle_edges=4, dwg_cut_layer_equal=True, csv_rows=1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path, help='三维开孔样件浏览器验收输出目录')
    folder = parser.parse_args().folder.resolve()
    proof = json.dumps(verify(folder), ensure_ascii=False, indent=2) + '\n'
    (folder / '出图回读.json').write_text(proof, encoding='utf-8')
    print(proof, end='')
