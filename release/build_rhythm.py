"""Build a standalone rhythm EXE using the local, validated JumpRope launcher."""
from pathlib import Path
import shutil,zipfile,hashlib,json,struct,subprocess,tempfile
from runtime_dependencies import collect
from runtime_metadata import collect_metadata
ROOT=Path(__file__).resolve().parents[1]
PY=ROOT/'.conda';SITE=PY/'Lib/site-packages'
OUT=ROOT/'release/output/HololiveRhythm-1.0.8';OUT.mkdir(parents=True,exist_ok=True)
(ROOT/'release/build').mkdir(parents=True,exist_ok=True)
DEST=Path(tempfile.mkdtemp(prefix='rhythm-1.0.8-',dir=ROOT/'release/build'))
def cp(a,b):
    b.parent.mkdir(parents=True,exist_ok=True)
    if a.is_dir():shutil.copytree(a,b,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests','test','*.pyc','*.pdb','*.lib'))
    else:shutil.copy2(a,b)
app=DEST/'app';runtime=DEST/'runtime';natives=runtime/'natives'
for folder in (app,runtime,natives):folder.mkdir(parents=True,exist_ok=True)
cp(ROOT/'src',app/'src')
for name in ['gui/release_gui.py','tools/run_multi_live.py','run_rhythm_tuning.cmd','run_rhythm_mechanism_test.cmd','domains/hololive_dreams/models/rhythm/rhythm_game.py','domains/hololive_dreams/models/rhythm/rhythm_game_config.json']:
    cp(ROOT/name,app/name)
for name in ['ui_features','multi_live','world_reference/20261021']:
    cp(ROOT/'domains/hololive_dreams/data'/name,app/'domains/hololive_dreams/data'/name)
for name in ['python.exe','pythonw.exe','python312.dll','python3.dll','LICENSE_PYTHON.txt','zlib.dll','vcruntime140.dll','vcruntime140_1.dll']:
    cp(PY/name,runtime/name)
with zipfile.ZipFile(runtime/'python312.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for p in (PY/'Lib').rglob('*.py'):
        rel=p.relative_to(PY/'Lib')
        if not any(x in ('site-packages','tests','test','__pycache__','ensurepip','idlelib','turtledemo') for x in rel.parts):archive.write(p,str(rel))
(runtime/'python312._pth').write_text('python312.zip\n.\nDLLs\nLib/site-packages\n../app\nimport site\n',encoding='utf-8')
for p in (PY/'DLLs').glob('*.pyd'):cp(p,runtime/'DLLs'/p.name)
packages=['numpy','numpy.libs','cv2','mss','dxcam','comtypes','rapidocr_onnxruntime','onnxruntime','pyclipper','shapely','shapely.libs','yaml','PIL','six.py','tqdm','packaging','coloredlogs','humanfriendly','flatbuffers','sympy','mpmath','google/protobuf']
for name in packages:
    if (SITE/name).exists():cp(SITE/name,runtime/'Lib/site-packages'/name)
metadata_report=collect_metadata(SITE,runtime/'Lib/site-packages',packages)
for name in ['tcl8.6','tk8.6']:cp(PY/'Library/lib'/name,runtime/'tcl'/name)
for name in ['tcl86t.dll','tk86t.dll']:cp(PY/'Library/bin'/name,natives/name)
native_report=collect(runtime,PY)
cp(ROOT/'release/runtime_sitecustomize.py',runtime/'sitecustomize.py')
for folder in SITE.glob('*.dist-info'):
    if any(folder.name.lower().startswith(n.split('/')[0].replace('.py','').replace('.libs','').lower()+'-') for n in packages) or folder.name.lower().startswith(('opencv_python-','pyyaml-','pillow-')):
        for p in folder.rglob('*'):
            if p.is_file() and ('license' in p.name.lower() or 'notice' in p.name.lower()):cp(p,DEST/'licenses'/folder.name/p.relative_to(folder))
cp(ROOT/'release/rhythm_bootstrap.py',DEST/'bootstrap.py')
cp(ROOT/'release/runtime_probe.py',DEST/'runtime_probe.py')
cp(ROOT/'release/capture_cleanup_probe.py',DEST/'capture_cleanup_probe.py')
manifest=[hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(DEST).as_posix() for p in sorted(DEST.rglob('*')) if p.is_file() and p.name!='MANIFEST.sha256']
(DEST/'MANIFEST.sha256').write_text('\n'.join(manifest)+'\n',encoding='utf-8')
payload=ROOT/'release/build/rhythm-payload.zip'
with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for p in sorted(DEST.rglob('*')):
        if p.is_file():archive.write(p,p.relative_to(DEST).as_posix())
digest=hashlib.sha256(payload.read_bytes()).hexdigest()
launcher=(ROOT/'release/RhythmLauncher.cs').read_text(encoding='utf-8-sig').replace('__PAYLOAD_SHA__',digest).replace('JumpRopeAssistant','HololiveRhythm').replace('JumpRopeRelease-','HololiveRhythm-').replace('跳绳助手','自动打歌助手')
cs=ROOT/'release/build/RhythmLauncher.cs';cs.write_text(launcher,encoding='utf-8-sig')
exe=OUT/'HololiveRhythm-1.0.8.exe'
subprocess.run(['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe','/nologo','/target:winexe','/platform:x64','/optimize+','/out:'+str(exe),'/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll',str(cs)],check=True)
with exe.open('ab') as target,payload.open('rb') as src:
    shutil.copyfileobj(src,target);target.write(struct.pack('<Q',payload.stat().st_size));target.write(b'JROPE001')
report={'exe':str(exe),'bytes':exe.stat().st_size,'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'payload_sha256':digest,'platform':'Windows x64','gameplay_tested':False}
(OUT/'build-info.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
