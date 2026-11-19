"""NODO's local CAD worker. Polls the private exchange, with no network listener."""
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / '.nodo-draw'
ENGINE = ROOT / 'engineering' / 'ae-cabinet'
EXCHANGE = ROOT / 'exchange'
VENDOR = ENGINE / 'vendor' / 'freecad-library'
HARDWARE = ROOT.parent / 'addons' / 'nodo_draw' / 'data' / 'hardware'
T_PLATE_HASH = '2af625067f0dfa31d1b251fdf9546af8e92db33947dd4a911f231ff0bcc7fae1'


def read(path):
    return json.loads(path.read_text('utf-8'))


def publish(path, value):
    tmp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), 'utf-8')
    os.replace(tmp, path)


def install_assets(work, parameters):
    for item in parameters['accessories']:
        model = item['definition']
        if model['kind'] != 'step':
            continue
        digest = model['assetHash']
        if not re.fullmatch('[0-9a-f]{64}', digest) or model.get('assetPath') != f'library/{digest}.step':
            raise ValueError('模型版本引用无效')
        source = (VENDOR / 'fc-plate-t5' / 'T_shaped_5_holes-Plate.step'
                  if digest == T_PLATE_HASH else HARDWARE / (digest + '.step'))
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('附件 STEP 校验值与选用版本不一致')
        (work / 'library').mkdir(exist_ok=True)
        shutil.copyfile(source, work / model['assetPath'])


def make_outputs(work, payload):
    result = read(work / 'result.json')
    if not result['validation']['stepReadback']['valid'] or not result['validation']['package']['crcVerified']:
        raise ValueError('CAD 成果回读未通过')
    sheets = result['drawings']
    parts = [r for sheet in sheets if sheet['category'] == 'bom' for r in sheet['coordinates'][1:]]
    if len(parts) != len(result['parts']):
        raise ValueError('明细表行数与生成的零件实例不一致')
    with (work / 'bom.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['序号','零件名称','型号 / 图号','材料 / 牌号','板厚 mm','单台用量','订单总量','依据状态'])
        for index, name, code, mat, gauge, qty, basis in parts:
            writer.writerow([index, name, code, mat, gauge, qty, int(qty)*payload['quantity'], basis])

    archive = work / 'cabinet-drawings.zip'
    with zipfile.ZipFile(archive, 'a', zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(work / 'bom.csv','零件清单.csv')
        if (work / 'library').exists():
            for part in (work / 'library').glob('*.step'):
                bundle.write(part, 'library/' + part.name)
            if (work / 'library' / (T_PLATE_HASH + '.step')).is_file():
                for name in ('ATTRIBUTION.md','LICENSE-Assets.txt'):
                    bundle.write(VENDOR / name, 'licenses/FreeCAD-library/' + name)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip():
            raise ValueError('交付包 CRC 检查失败')
    files = {'step':'model.step','bom':'bom.csv','bundle':archive.name,'holes':'hole-coordinates.csv','mesh':'mesh.json'}
    rows = []
    for index, sheet in enumerate(sheets):
        key = f'd{index+1}'
        files[key] = sheet['dwg']
        files[key+'p'] = sheet['preview']
        if sheet['category'] == 'flat':
            files[key+'c'] = 'cuts/' + sheet['part'] + '.dxf'
        rows.append({'key':key,'name':sheet['name'],'category':sheet['category']})
    if any(not (work / name).is_file() for name in files.values()):
        raise ValueError('交付包文件不完整')
    return dict(files=files, sheets=rows, parts=len(parts), limits=result['limitations'],
                cut_count=sum(s['category']=='flat' for s in sheets),
                dims=result['validation']['cabinetSize'], step_solids=result['validation']['stepReadback']['solids'])


def run_job(folder, uv):
    status = folder / 'status.json'
    if status.is_file() and read(status)['state'] in ('done','failed'):
        return
    payload = read(folder / 'request.json')
    work = folder / ('run-' + uuid.uuid4().hex)
    work.mkdir()
    state = dict(state='running', run=work.name, stage='准备工程参数', progress=1)
    publish(status, state)
    try:
        p = payload['parameters']
        preview = payload['operation'] == 'preview'
        install_assets(work, p)
        if not preview and (work/'library').exists():
            # The engine enters the component script's directory for each native STEP.
            # Mirror the relative library there so published parameters stay portable.
            shutil.copytree(work/'library', work/'component-cache'/work.name/'library')
        publish(work / 'input.json', p)
        script = ENGINE / 'src/accessory_io.py' if preview else Path(__file__).with_name('build_cabinet.py')
        args = [str(script), str(work/'input.json'), str(work/'mesh.json' if preview else work)]
        args += ['--preview'] if preview else ['--component-root', str(work / 'component-cache')]
        env = {**os.environ, 'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1',
               'CADGEN_DAEMON':'0','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        log = work / 'engine.log'
        with log.open('wb') as out:
            subprocess.run([uv, 'tool','run','--offline','--no-config','--managed-python','--python',
                            '3.13','--from','cadgen==0.7.26','python',*args], cwd=work, env=env,
                           stdout=out, stderr=subprocess.STDOUT, check=True, timeout=3600,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if preview:
            mesh = read(work/'mesh.json')
            issues = [v['message'] for v in mesh.get('accessoryValidation',{}).get('issues',[])]
            info = {'files':{'mesh':'mesh.json'},'issues':issues}
        else:
            info = make_outputs(work, payload)
        publish(status, {**state,'state':'done','stage':'已生成','progress':100,**info})
    except Exception as exc:
        error = str(exc)
        if (work/'error.json').exists():
            error = read(work/'error.json')['error']
        elif isinstance(exc, subprocess.CalledProcessError):
            loglines=(work/'engine.log').read_text('utf-8',errors='replace').splitlines()
            error = next((s.split(': ',1)[-1] for s in reversed(loglines) if s.strip()), '工程引擎异常')
        publish(status,{**state,'state':'failed','stage':'生成失败','error':error[:600]})


def heartbeat():
    while True:
        publish(EXCHANGE/'worker.json', {'time':time.time()})
        time.sleep(5)


def serve():
    import msvcrt
    uv = shutil.which('uv')
    oda = Path(os.getenv('AE_ODA_CONVERTER',r'C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe'))
    if not uv or not oda.is_file() or not (ENGINE/'build.py').is_file():
        sys.exit('缺少 NODO 工程资源、CAD Python 环境或 DWG 转换器')
    EXCHANGE.mkdir(exist_ok=True)
    with (ROOT/'worker.lock').open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        threading.Thread(target=heartbeat, daemon=True).start()
        while True:
            jobs = sorted(EXCHANGE.glob('*/request.json'),key=lambda f:f.stat().st_mtime)
            for job in jobs:
                if re.fullmatch('[0-9a-f]{32}',job.parent.name):
                    try:
                        run_job(job.parent, uv)
                    except (OSError, ValueError) as exc:
                        print(str(exc), file=sys.stderr, flush=True)
            time.sleep(.8)


if __name__ == '__main__':
    serve()
