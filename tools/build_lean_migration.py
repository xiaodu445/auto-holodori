"""Build a lean, hashed migration snapshot without changing source data."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
H=ROOT/'learning/jump_rope_yolo'
SKIP={'.conda','.venv','.git','__pycache__','.pytest_cache','.codex','.agents','node_modules','migration_packages'}
TEXT={'.py','.json','.md','.txt','.toml','.cmd','.js','.html','.yaml','.yml','.gitignore'}
SECRET=re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|AIza[A-Za-z0-9_-]{30,})')

def walk(folder):
    for base,ds,fs in os.walk(folder):
        ds[:]=[d for d in ds if d not in SKIP and not (Path(base)/d).is_symlink()]
        for name in fs:
            p=Path(base)/name
            if not p.is_symlink() and not name.endswith(('.pyc','.pyo','.cache')) and not name.startswith('.env'):yield p

def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k.lower() not in {'api_key','api_key_file','access_token','refresh_token','password','secret','token'}}
    if isinstance(value,list):return [clean(v) for v in value]
    return value

def main():
    out=ROOT/'migration_packages'/('gameagent-lean-'+datetime.now().strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
    selected={};excluded=[]
    def add(p,part='code'):selected[p.relative_to(ROOT).as_posix()]=(p,part)
    for name in ['config','docs','domains','knowledge','prompts','skills','src','tests','tools']:
        for p in walk(ROOT/name):add(p)
    for p in ROOT.iterdir():
        if p.is_file():add(p)
    allowed_cmd={'run_game_jump.cmd','view_game_jump.cmd','view_history.cmd','view_history_pytorch.cmd','view_history_tensorrt.cmd'}
    for p in walk(ROOT/'learning'):
        rel=p.relative_to(ROOT/'learning')
        if any(x in {'results','datasets','runs','engines','weights','downloads','.ultralytics'} for x in rel.parts):continue
        if p.suffix.lower() in {'.pt','.onnx','.engine','.avi','.mp4','.log'}:continue
        if p.suffix.lower()=='.cmd' and p.parent==H and p.name not in allowed_cmd:continue
        add(p)
    dataset=H/'datasets/temporal-trial-07'
    for p in walk(dataset):add(p,'assets')
    add(H/'runs/temporal-history-07-late/weights/last.pt','assets')
    recording=ROOT/'runtime/jump-rope/recordings/20261006-115004-094950'
    for name in ['screen.avi','timestamps.json']:add(recording/name,'assets')
    manifest=json.loads((dataset/'MANIFEST.json').read_text(encoding='utf-8'))
    frames={f for r in manifest['frames'] for f in [r['frame'],*r['history_frames']]}
    exact=ROOT/'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames'
    for f in sorted(frames):add(exact/f'{f:06d}.jpg','assets')
    # Full recording retained; exact JPEG subset preserves original training pixels/hashes.
    records=[];mapping={};transformed=[]
    for part in ['code','assets']:
        archive=out/f'Game_agent-{part}.zip'
        with zipfile.ZipFile(archive,'w',allowZip64=True) as z:
            entries=[(rel,p) for rel,(p,k) in selected.items() if k==part]
            for i,(rel,p) in enumerate(sorted(entries)):
                payload=None
                if p.suffix.lower() in TEXT and p.stat().st_size<40*1024**2:
                    payload=p.read_bytes()
                    if SECRET.search(payload):excluded.append(dict(path=rel,reason='credential-like literal; omitted'));continue
                    if rel in {'config/model.json','config/models.json'}:
                        payload=json.dumps(clean(json.loads(payload.decode('utf-8-sig'))),ensure_ascii=False,indent=2).encode();transformed.append(rel)
                    if p.parent==H and p.name in allowed_cmd:
                        payload=payload.replace(b'runs\\temporal-control-05\\weights\\last.pt',b'runs\\temporal-history-07-late\\weights\\last.pt');transformed.append(rel)
                kind=zipfile.ZIP_DEFLATED if p.suffix.lower() in TEXT else zipfile.ZIP_STORED
                sha=hashlib.sha256();count=0
                info=zipfile.ZipInfo('Game_agent/'+rel,date_time=datetime.fromtimestamp(p.stat().st_mtime).timetuple()[:6]);info.compress_type=kind
                with z.open(info,'w',force_zip64=True) as dst:
                    if payload is not None:dst.write(payload);sha.update(payload);count=len(payload)
                    else:
                        with p.open('rb') as src:
                            while chunk:=src.read(8*1024**2):dst.write(chunk);sha.update(chunk);count+=len(chunk)
                records.append(dict(path=rel,archive=archive.name,bytes=count,sha256=sha.hexdigest()))
                if i%100==0:print(part,i,len(entries),rel,flush=True)
        mapping[part]=dict(file=archive.name,bytes=archive.stat().st_size,sha256=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest())
    report=dict(archives=mapping,files=records,exact_frames=len(frames),training_frames=170,evaluation_frames=27,transformed=transformed,
                omitted=excluded,policy='Code for whole Game_agent; latest YOLO07 PT only; latest170/27dataset; one original recording; original exact JPEG subset. No environments, downloads, previous models, TRT engines, private runtime logs or historical outputs.')
    (out/'MANIFEST.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for archive in mapping.values():
        with zipfile.ZipFile(out/archive['file']) as z:
            bad=z.testzip();assert bad is None,bad
    (out/'VERIFIED.json').write_text(json.dumps(dict(zip_crc='all files passed',archives=mapping),indent=2),encoding='utf-8')
    print('COMPLETE',out,flush=True)

if __name__=='__main__':main()
