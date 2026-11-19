"""Check a browser-downloaded AE acceptance package against its physical CAD files."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from itertools import pairwise
from pathlib import Path

import ezdxf
from cadgen import build123d as bd

ENGINE = Path(__file__).resolve().parents[2] / '.nodo-draw' / 'engineering' / 'ae-cabinet'
sys.path.insert(0, str(ENGINE / 'src'))
from drawings import signature
from flat_style import verify as verify_flat

CASES = {
    'AE-101': dict(kind='single', door='door', size=(420, 235, 340), quantity=2,
                   uv=(95, 110), xy=(107.82, 121.6), radius=9, sheets=18, cuts=7, parts=21),
    'AE-202': dict(kind='double', door='door_right', size=(1020, 320, 720), quantity=1,
                   uv=(135, 155), xy=(147.82, 166.6), half_rect=(22, 11), sheets=20, cuts=7, parts=25),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def near(a, b, tolerance=1e-4):
    return len(a) == len(b) and all(abs(x-y) <= tolerance for x, y in zip(a, b))


def step_leaves(node):
    if not node.children:
        yield node
    for child in node.children:
        yield from step_leaves(child)


def rows(file):
    with file.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.reader(stream))


def verify_holes(case, holes, door_step, cut_doc, properties):
    face = next(f for f in properties['faces'] if f['id'] == case['door'])
    cut = cut_doc.modelspace()
    circles = [(e.dxf.center.x,e.dxf.center.y,e.dxf.radius) for e in cut.query('CIRCLE')]
    segments = [(tuple(e.dxf.start)[:2],tuple(e.dxf.end)[:2]) for e in cut.query('LINE')]
    manual = next(h for h in holes if h[0] == 'H1')
    owned = [h for h in holes if h[0].startswith('a1n1_')]
    require(len(owned) == 5, 'T 形附件的五个安装孔不完整')
    require(near(tuple(map(float, manual[4:6])), case['uv']), '板面坐标与实测输入不同')
    require(near(tuple(map(float, manual[6:8])), case['xy']), '展开坐标与该门板基准不同')
    for h in [manual, *owned]:
        require(h[2] == case['door'], '孔位出现在错误的门板')
        center = tuple(map(float, h[12:15]))
        u,v = map(float, h[4:6])
        expected = [o+u*a+v*b for o,a,b in zip(face['origin'],face['uAxis'],face['vAxis'])]
        require(near(center, expected), '三维孔中心与板面基准不一致')
        half_x = 2.75 if h is not manual else case.get('radius', 22)
        half_y = 2.75 if h is not manual else case.get('radius', 11)
        def metal(du, dv):
            point = [c-n*face['thickness']/2+du*a+dv*b for c,n,a,b in
                     zip(center,face['normal'],face['uAxis'],face['vAxis'])]
            return door_step.is_inside(point)
        require(not metal(0,0) and not metal(half_x-.3,0) and not metal(0,half_y-.3)
                and metal(half_x+.3,0) and metal(0,half_y+.3), f'{h[0]} 的 STEP 穿孔或边界不符')
        x,y = map(float,h[6:8])
        if h is manual and 'half_rect' in case:
            corners = [(x-half_x,y-half_y),(x+half_x,y-half_y),(x+half_x,y+half_y),(x-half_x,y+half_y)]
            for a,b in pairwise(corners+[corners[0]]):
                require(any((near(a,c) and near(b,d)) or (near(a,d) and near(b,c)) for c,d in segments),
                        '切割 DXF 缺少矩形孔边线')
        else:
            require(any(near((x,y,half_x),circle) for circle in circles), f'切割 DXF 缺少 {h[0]} 圆孔')
    return {'face':case['door'], 'uv':case['uv'], 'flatXY':case['xy'],
            'world':list(map(float, manual[12:15])), 'accessory_holes':len(owned)}


def check_sample(folder, temp):
    case = CASES[folder.name]
    oda = Path(os.environ.get('AE_ODA_CONVERTER',r'C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe'))
    dwgs, back = temp / 'dwg', temp / 'readback'
    dwgs.mkdir()
    back.mkdir()
    with zipfile.ZipFile(folder / '工程图包.zip') as archive:
        require(archive.testzip() is None, '工程图包 CRC 错误')
        result = json.loads(archive.read('result.json'))
        p = json.loads(archive.read('parameters.json'))
        door = case['door']
        originals = {'整柜.step':'model.step', '门板展开.dwg':f'dwg/{door}.dwg',
                     '门板切割.dxf':f'cuts/{door}.dxf', '孔位表.csv':'hole-coordinates.csv','零件清单.csv':'零件清单.csv'}
        for local, internal in originals.items():
            require((folder / local).read_bytes() == archive.read(internal), '独立下载与整包版本不符 '+local)
        require(near((p['width'],p['depth'],p['height']),case['size']) and p['configuration']['kind']==case['kind'],
                '归档柜型或规格不符')
        sheets = result['drawings']
        counts = Counter(s['category'] for s in sheets)
        require(len(sheets)==case['sheets'] and counts['flat']==case['cuts'], '图纸张数与样例不符')
        for s in sheets:
            data = archive.read(s['dwg'])
            require(data[:6]==b'AC1032' and hashlib.sha256(data).hexdigest()==s['sha256'], 'DWG 格式或版本摘要错误')
            (dwgs / Path(s['dwg']).name).write_bytes(data)
        subprocess.run([str(oda),str(dwgs),str(back),'ACAD2018','DXF','0','1','*.dwg'],
                       check=True, timeout=240, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        require(len(list(back.glob('*.dxf')))==len(sheets), 'DWG 重新转换后张数不符')
        for s in sheets:
            readback = back / (s['part']+'.dxf')
            doc = ezdxf.readfile(readback)
            require(len(doc.modelspace()) and s['validation']['roundtripGeometryEqual'], 'DWG 图元或往返记录缺失')
            if s['category'] == 'bom':
                printed = {e.plain_text() for e in doc.modelspace().query('TEXT MTEXT')}
                require(all(row[1] in printed for row in s['coordinates'][1:]), '零件名称与 DWG 实际文字不符')
            if s['category'] == 'flat':
                # Run the original paper, colour, material caption and native-dimension
                # rules on a fresh conversion of the downloaded binary DWG.
                verify_flat(readback,readback,s)
                cut = temp / (s['part']+'-cut.dxf')
                cut.write_bytes(archive.read('cuts/'+s['part']+'.dxf'))
                cnc = ezdxf.readfile(cut)
                require(cnc.units==4 and all(e.dxf.layer=='CUT' for e in cnc.modelspace()), '切割文件混入非加工图层')
                require(Counter(map(signature,cnc.modelspace())) ==
                        Counter(signature(e) for e in doc.modelspace() if e.dxf.layer=='CUT'),
                        '切割 DXF 与展开 DWG 的毫米轮廓不一致')
        t_plate = p['accessories'][0]['definition']
        require(hashlib.sha256(archive.read(t_plate['assetPath'])).hexdigest()==t_plate['assetHash'],
                '附件库 STEP 与所选附件版本不符')

    model = bd.import_step(folder/'整柜.step')
    parts = {p.label:p for p in step_leaves(model)}
    require(model.is_valid and len(model.solids())==case['parts'], 'STEP 实体无效或数量不符')
    base = bd.Compound(children=[parts[r['id']] for r in result['parts'] if not r.get('accessoryId')])
    require(near(list(base.bounding_box().size),case['size']), '箱体实际尺寸与设计不符')
    require(near(list(parts['a1n1_model'].bounding_box().size),(55,4,60)), '固定附件被缩放或安装方向错误')
    if case['kind']=='single':
        proof = sheets[0]['validation']
        require(proof['assemblyEnvelopeSource']=='model.step' and len(proof['sixViews'])==6,
                '含顶罩的总装六视图未通过 STEP 外廓回读')
    bom = rows(folder/'零件清单.csv')[1:]
    drawn_rows = [r for s in sheets if s['category']=='bom' for r in s['coordinates'][1:]]
    require(len(bom)==len(drawn_rows)==case['parts'], '零件清单行数与 DWG 明细表不符')
    for entry, native in zip(bom, drawn_rows):
        require(entry[:6]==native[:6] and entry[7]==native[6] and
                int(entry[6])==int(entry[5])*case['quantity'], '图号、材料、板厚或订单总量不符')
    require(any(r[1]=='T 形五孔连接板' for r in bom), '附件名称错误')
    if case['kind']=='single':
        require(any(r[1]=='平板防尘罩 · 罩板' for r in bom), '防尘罩板名称错误')
    holes = verify_holes(case,rows(folder/'孔位表.csv')[1:],parts[door],ezdxf.readfile(folder/'门板切割.dxf'),result)
    return dict(source=folder.name, revision=p['revision'], size_WDH=case['size'],
                assembled_WDH=[round(n,4) for n in model.bounding_box().size], solids=len(model.solids()),
                dwg=len(sheets),cut_dxf=counts['flat'],bom_rows=len(bom),order_quantity=case['quantity'],
                total_parts=sum(int(r[6]) for r in bom),manual_hole=holes,
                engineering_status=result['engineeringStatus'])


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path, help='从技术工作台下载的 AE-101 或 AE-202 样例文件夹')
    args=parser.parse_args()
    folder=args.folder.resolve()
    with tempfile.TemporaryDirectory(prefix='nodo-draw-check-') as temp:
        proof=check_sample(folder,Path(temp))
    receipt=json.dumps(proof,ensure_ascii=False,indent=2)
    (folder/'核对结果.json').write_text(receipt,encoding='utf-8')
    print(receipt)
