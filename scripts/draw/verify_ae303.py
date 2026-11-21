"""Independently accept AE-303 handoff 2 from its browser downloads."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import dist
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from verify_sample import ENGINE, bd, ezdxf, near, require, rows, signature, step_leaves
from assembly_template import project_point
from build_cabinet import check_assembly
from cadgen.drawing_checks import validate_dxf_file
from drawings import verify_roundtrip
from sheet_parameters import thickness


FILES = {
    '整柜.step': 'model.step', '零件清单.csv': '零件清单.csv', '孔位表.csv': 'hole-coordinates.csv',
    '总装图.dwg': 'dwg/assembly.dwg', '门板展开.dwg': 'dwg/door.dwg', '门板切割.dxf': 'cuts/door.dxf',
}
BOM = [
    ('a1n1', 'AE-SQ35', 'door', 1), ('a2n1', 'T5-55', 'mount', 1),
    ('a3n1', 'EX-COVER', 'top', 5), ('a4n1', 'EX-BASE', 'bottom', 5),
]


def dwg_readback(archive, drawings, run, temp):
    dwg, readback = temp / 'dwg', temp / 'readback'
    dwg.mkdir()
    readback.mkdir()
    for sheet in drawings:
        data = archive.read(sheet['dwg'])
        require(data[:6] == b'AC1032' and sha256(data).hexdigest() == sheet['sha256'], 'DWG 原生格式或摘要异常')
        (dwg / Path(sheet['dwg']).name).write_bytes(data)
    oda = os.environ.get('AE_ODA_CONVERTER', r'C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe')
    subprocess.run([oda, str(dwg), str(readback), 'ACAD2018', 'DXF', '0', '1', '*.dwg'],
                   check=True, timeout=240, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(len(list(readback.glob('*.dxf'))) == len(drawings), 'ODA 回读图纸数量不同')
    documents, cuts, proofs = {}, {}, {}
    for sheet in drawings:
        ident = sheet['part']
        fresh = readback / (ident + '.dxf')
        source = run / 'drawing' / fresh.name
        doc = documents[ident] = ezdxf.readfile(fresh)
        require(doc.units == 4, ident + ' 单位不是毫米')
        if ident == 'assembly':
            proof = check_assembly(source, fresh, sheet, run, verify_roundtrip)
        else:
            proof = verify_roundtrip(source, fresh, sheet)
        require(proof['roundtripGeometryEqual'], ident + ' 回读几何不一致')
        proofs[ident] = proof
        if sheet['category'] == 'flat':
            cut = temp / (ident + '-cut.dxf')
            cut.write_bytes(archive.read('cuts/' + ident + '.dxf'))
            cnc = cuts[ident] = ezdxf.readfile(cut)
            require(cnc.units == 4 and all(e.dxf.layer == 'CUT' for e in cnc.modelspace()), '切割文件单位或图层错误')
            require(not validate_dxf_file(str(cut)), ident + ' 切割轮廓未闭合或存在重复线')
            require(Counter(map(signature, cnc.modelspace())) ==
                    Counter(signature(e) for e in doc.modelspace() if e.dxf.layer == 'CUT'),
                    ident + ' 的切割 DXF 与 DWG CUT 层不同')
    return documents, cuts, proofs


def loops(lines):
    # This door pattern has linear profiles. Count edges in both directions
    # before building connected contours so an identical second cut is visible.
    adjacency = defaultdict(set)
    edges = set()
    for line in lines:
        a, b = [tuple(round(v, 5) for v in point) for point in (line.dxf.start, line.dxf.end)]
        edge = tuple(sorted((a, b)))
        require(a != b and a[2] == b[2] == 0 and edge not in edges, '门板存在重合、零长或非平面刀线')
        edges.add(edge)
        adjacency[a].add(b)
        adjacency[b].add(a)
    require(all(len(ns) == 2 for ns in adjacency.values()), '门板轮廓存在开口或分叉')
    pending, result = set(adjacency), []
    while pending:
        start = next(iter(pending))
        points = {start}
        previous, current = start, next(iter(adjacency[start]))
        while current != start:
            require(current not in points, '门板轮廓异常回环')
            points.add(current)
            previous, current = current, next(iter(adjacency[current] - {previous}))
        pending -= points
        result.append((len(points), [min(p[i] for p in points) for i in (0, 1)],
                       [max(p[i] for p in points) for i in (0, 1)]))
    return sorted(result, reverse=True)


def verify_door(cut, door, lock, p, holes):
    original = ezdxf.readfile(ENGINE / 'converted' / 'AE04.380.300.01-门板展开图.dxf')
    baseline = loops(original.modelspace().query('LINE'))
    drawing = list(cut.modelspace())
    require(all(e.dxftype() == 'LINE' for e in drawing), '门板多出旧版以外的加工图元')
    current = loops(drawing)
    require([n for n, _, _ in baseline] == [n for n, _, _ in current] == [20, 4], '门板应仅有外框与一个四边方孔')
    _, base, _ = baseline[0]
    _, old_low, old_high = baseline[1]
    _, low, high = current[1]
    shift = (p['width'] - 380, (p['height'] - 300) / 2)
    require(near(low, [v-b+d for v,b,d in zip(old_low,base,shift)]) and
            near(high, [v-b+d for v,b,d in zip(old_high,base,shift)]), '方孔位置与原图展开基准不符')
    size = [round(b-a,5) for a,b in zip(low,high)]
    require(size == [21.2,21.2] and not any(h[2] == 'door' for h in holes), '方锁带入了额外门板加工孔')
    center = [p['width'] - 55, p['height'] / 2]
    panel_thickness = thickness(p, 'door')
    for y in (panel_thickness*.25, panel_thickness*.5, panel_thickness*.75):
        require(not door.is_inside((center[0],y,center[1])) and lock.is_inside((center[0],y,center[1])), '方锁未正确穿过门板')
        for axis in (0,1):
            for sign in (-1,1):
                def sample(offset):
                    x,z = center[:]
                    return (x + sign*offset if axis == 0 else x, y, z + sign*offset if axis == 1 else z)
                require(not door.is_inside(sample(10.599)) and door.is_inside(sample(10.601)), 'STEP 方孔边界超差')
                require(lock.is_inside(sample(10.499)) and not lock.is_inside(sample(10.501)), 'STEP 锁颈尺寸超差')
    return dict(cut_contours=2, lock_contours=1, lock_edges=4, duplicate_edges=0, size_mm=size,
                flat_xy_mm=[round((a+b)/2,5) for a,b in zip(low,high)],
                world_on_door_mm=[center[0],0,center[1]], neck_mm=21, nominal_clearance_per_side_mm=.1)


def bounds(solid):
    box = solid.bounding_box()
    return [list(box.min), list(box.max)]


def verify_fittings(result, solids, holes, cuts, documents):
    p = result['parameters']
    instances = [(a['id'],a['definition']['code'],a['face']) for a in p['accessories']]
    require(instances == [item[:3] for item in BOM], '四类五金实例或安装面不一致')
    counts = Counter(part['accessoryId'] for part in result['parts'] if part.get('accessoryId'))
    require(counts == Counter({ident:count for ident,_,_,count in BOM}), 'STEP 附件组成件与 BOM 不符')
    placements = {
        'a1n1_model': [[347.5,-5,152.5],[395,21,187.5]],
        'a2n1_model': [[182.5,203.5,140],[237.5,207.5,200]],
        'a3n1_plate': [[-12,-12,380],[432,247,381.5]],
        'a4n1_front': [[0,0,-70],[420,2,-2]], 'a4n1_back': [[0,233,-70],[420,235,-2]],
        'a4n1_left': [[0,2,-70],[2,233,-2]], 'a4n1_right': [[418,2,-70],[420,233,-2]],
        'a4n1_plate': [[0,0,-2],[420,235,0]],
    }
    for i,(x,y) in enumerate(((41.5,193.4),(378.5,193.4),(41.5,62.5),(378.5,62.5)),1):
        placements[f'a3n1_post{i}'] = [[x-6,y-6,340],[x+6,y+6,380]]
    measured = {}
    for ident,expected in placements.items():
        actual = bounds(solids[ident])
        require(all(near(a,b) for a,b in zip(actual,expected)), ident+' 的 STEP 装配位置不符')
        measured[ident] = [[round(n,5) for n in pt] for pt in actual]
    require(near(bounds(solids['mount'])[0],(27.5,207.5,17.5)), 'T 形板与安装板贴合基准不符')
    require(Counter(h[2] for h in holes) == {'mount':5,'top':4,'bottom':4}, '安装孔位表数量不符')
    mount = next(s for s in result['drawings'] if s['part'] == 'formed_mount')['formedLayout']['views'][0]
    mount_curves = [e for e in documents['formed_mount'].modelspace().query('CIRCLE ARC')
                    if e.dxf.layer == mount['visibleLayer']]
    for row in holes:
        face = row[2]
        x,y,z = (float(v) for v in row[12:15])
        u,v = (float(n) for n in row[6:8])
        radius = 2.75 if face == 'mount' else 3.5
        require(any(near([*tuple(e.dxf.center)[:2],e.dxf.radius],(u,v,radius))
                    for e in cuts[face].modelspace().query('CIRCLE')), row[0]+' 缺少切割圆孔')
        if face == 'mount':
            center = project_point(mount,(x,y,z))
            require(any(near([*tuple(e.dxf.center)[:2],e.dxf.radius],(*center,radius))
                        for e in mount_curves), row[0]+' 的安装板正视位置错误')
            pair = [(solids['mount'],(x,y+1.25,z)),(solids['a2n1_model'],(x,y-2,z))]
        elif face == 'top':
            pair = [(solids['top'],(x,y,z-.75)),(solids['a3n1_plate'],(x,y,380.75))]
        else:
            pair = [(solids['bottom'],(x,y,z+.75)),(solids['a4n1_plate'],(x,y,-1))]
        for solid,center in pair:
            require(not solid.is_inside(center) and solid.is_inside((center[0]+radius+.2,*center[1:])),
                    row[0]+' 的实体孔心或孔边不符')
    front = result['drawings'][0]['assemblyLayout']['views'][0]
    segments = [(tuple(e.dxf.start)[:2],tuple(e.dxf.end)[:2])
                for e in documents['assembly'].modelspace().query('LINE') if e.dxf.layer == front['visibleLayer']]
    for a,b in [((-12,-12,381.5),(432,-12,381.5)),((0,0,-70),(420,0,-70)),
                ((350.5,-5,187.5),(379.5,-5,187.5))]:
        a,b = project_point(front,a),project_point(front,b)
        require(any((near(a,c) and near(b,d)) or (near(a,d) and near(b,c)) for c,d in segments),
                '总装正视图中的罩板、底座或锁面盖与 STEP 位置不符')
    return [dict(code=code,surface=face,per_cabinet=1,components=count,
                 coordinates_mm={key:box for key,box in measured.items() if key.startswith(ident+'_')})
            for ident,code,face,count in BOM]


def verify_bom_rows(csv_rows, sheets, documents):
    batch = [s for s in sheets if s['category'] == 'bom']
    decoded = []
    for sheet in batch:
        text_rows = defaultdict(list)
        for e in documents[sheet['part']].modelspace().query('TEXT'):
            text_rows[round(e.dxf.insert.y,5)].append((e.dxf.insert.x,e.plain_text()))
        printed = [[text for _,text in sorted(text_rows[y])] for y in sorted(text_rows,reverse=True)
                   if len(text_rows[y])==7]
        require(printed == sheet['coordinates'], '实际 DWG 明细的名称、图号、材料、板厚或数量不符')
        decoded.extend(printed[1:])
    require(len(csv_rows)==len(decoded), 'CSV 与 DWG 明细行数不同')
    for csv_row,dwg in zip(csv_rows,decoded):
        require(csv_row[:6]==dwg[:6] and csv_row[7]==dwg[6], 'CSV 与 DWG 明细或数量不符')
    return [len(s['coordinates'])-1 for s in batch]


def verify_bom(csv_rows, sheets, documents):
    pages = verify_bom_rows(csv_rows, sheets, documents)
    require(pages == [24,3], '零件明细未按旧版 24 行分页')
    require(all(row[5:7] == ['1','1'] for row in csv_rows), '零件明细单台和订单数量不符')
    require(Counter(r[2] for r in csv_rows if r[2] in [a[1] for a in BOM]) ==
            Counter({code:count for _,code,_,count in BOM}), '四类五金的组成件未逐项列全')


def check(folder, run, temporary):
    receipt = json.loads((folder/'下载记录.json').read_bytes())
    require(type(receipt['design']) is int and receipt['design'] > 0 and receipt['handoff']==2, '下载源不是 AE-303 交接版 2')
    request = json.loads((run.parent/'request.json').read_bytes())
    require(request['source']=='AE-303' and request['source_version']=='2' and request['quantity']==1, '工单与下载版本不符')
    with zipfile.ZipFile(folder/'工程图包.zip') as archive:
        require(archive.testzip() is None, '图包 CRC 错误')
        for local,packed in FILES.items():
            require((folder/local).read_bytes()==archive.read(packed), '单独下载和整包不是同一版本')
        result = json.loads(archive.read('result.json'))
        p = json.loads(archive.read('parameters.json'))
        require(p==result['parameters'] and p['revision']==receipt['version']==request['parameters']['revision'], '工程参数版本不同')
        require(p['configuration']['templateId']=='AE-SINGLE-02' and [p[k] for k in ('width','height','depth')]==[420,340,235], '柜型规格不符')
        require((run/'model.step').read_bytes()==(folder/'整柜.step').read_bytes(), '总装校验依据与下载 STEP 不同')
        for a in p['accessories']:
            definition=a['definition']
            if definition['kind']=='step':
                require(sha256(archive.read(definition['assetPath'])).hexdigest()==definition['assetHash'], '附件库 STEP 版本摘要不符')
        documents,cuts,proofs = dwg_readback(archive,result['drawings'],run,temporary)
    model = bd.import_step(folder/'整柜.step')
    solids = {part.label:part for part in step_leaves(model)}
    require(model.is_valid and len(model.solids())==len(solids)==27 and
            set(solids)=={part['id'] for part in result['parts']}, 'STEP 具名实体数量与图纸清单不同')
    bare = bd.Compound(children=[solids[part['id']] for part in result['parts'] if not part.get('accessoryId')])
    require(near(list(bare.bounding_box().size),(420,235,340)), '裸柜外廓尺寸不符')
    require(near(list(model.bounding_box().size),(444,259,451.5)), '装配后总外廓尺寸不符')
    holes = rows(folder/'孔位表.csv')[1:]
    square = verify_door(cuts['door'],solids['door'],solids['a1n1_model'],p,holes)
    fittings = verify_fittings(result,solids,holes,cuts,documents)
    verify_bom(rows(folder/'零件清单.csv')[1:],result['drawings'],documents)
    return dict(source='AE-303',handoff=2,job=receipt['job'],revision=p['revision'],solids=27,
                cabinet_WDH_mm=[420,235,340],assembled_WDH_mm=[444,259,451.5],
                dwg=len(documents),cut_dxf=len(cuts),door_square=square,bom_rows=27,bom_pages=[24,3],
                fittings=fittings,installation_holes={'mount':5,'top':4,'bottom':4},
                assembly_views=proofs['assembly']['sixViews'],mount_view=proofs['formed_mount']['formedViews'],
                engineering_status=result['engineeringStatus'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path,help='浏览器的 AE-303 版本下载目录')
    parser.add_argument('run',type=Path,help='同一任务的计算目录，含 DWG 转换前的 DXF')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nodo-ae303-readback-') as temp:
        proof = check(args.folder,args.run,Path(temp))
    text = json.dumps(proof,ensure_ascii=False,indent=2)+'\n'
    (args.folder/'核对结果.json').write_text(text,encoding='utf-8')
    print(text)
