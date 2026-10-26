"""Create and verify a stable project snapshot without touching live environments."""
from pathlib import Path
from datetime import datetime
import hashlib,json,os,zipfile
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
SKIP={'.venv','.conda','__pycache__','.git','downloads','.ultralytics'}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
 return h.hexdigest()
def files_under(path):
 if path.is_file():yield path;return
 if not path.exists():return
 for base,dirs,files in os.walk(path):
  dirs[:]=[d for d in dirs if d not in SKIP and not (Path(base)/d).is_symlink()]
  for name in files:
   p=Path(base)/name
   if not p.is_symlink() and p.suffix not in ('.pyc','.pyo'):yield p

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT.parent/'packages');p.add_argument('--label',choices=['stable','compact'],default='stable');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 scopes=[ROOT/'learning/jump_rope_yolo',ROOT/'learning/jump_rope_single_frame',ROOT/'learning/jump_rope_smoothing',ROOT/'src',ROOT/'tools/jump_rope',ROOT/'runtime/jump-rope']
 scopes+=list((ROOT/'domains/hololive_dreams/data').glob('jump_rope*'))
 scopes+=list((ROOT/'domains/hololive_dreams/models').glob('jump_rope*'))
 scopes+=list(ROOT.glob('*jump_rope*.cmd'))+[ROOT/'pyproject.toml',ROOT/'LOCAL_SETUP.md',ROOT/'README.md']
 paths=sorted(set(p for scope in scopes for p in files_under(scope)))
 stamp=datetime.now().strftime('%Y%m%d-%H%M%S');archive=a.output/f'jump-rope-{a.label}-{stamp}.zip';manifest=[]
 print(f'Packing {len(paths)} files. Environments and downloadable caches excluded.',flush=True)
 with zipfile.ZipFile(archive,'x',allowZip64=True,compresslevel=1) as z:
  for i,path in enumerate(paths):
   rel=path.relative_to(ROOT).as_posix();digest=sha(path);size=path.stat().st_size
   stored=path.suffix.lower() in ('.jpg','.jpeg','.png','.avi','.mp4','.pt','.engine','.onnx','.zip')
   z.write(path,'Game_agent/'+rel,compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
   manifest.append({'path':rel,'size':size,'sha256':digest})
   if i%500==0 or size>100*2**20:print(f'Packed {i+1}/{len(paths)}: {rel}',flush=True)
  z.writestr('MANIFEST.json',json.dumps({'version':'user-accepted-stable-2026-10-16','files':manifest,'excluded':['Python environments (kept on disk)','downloadable installers/wheels','interpreter caches'],'note':'Untested score-correction proposal is not included. Current behavior preserved.'},ensure_ascii=False,indent=2))
 print('Verifying archived bytes against SHA256 manifest...',flush=True)
 with zipfile.ZipFile(archive) as z:
  for i,row in enumerate(manifest):
   h=hashlib.sha256()
   with z.open('Game_agent/'+row['path']) as f:
    for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
   if h.hexdigest()!=row['sha256']:raise RuntimeError('Archive verification failed: '+row['path'])
   if i%1000==0:print(f'Verified {i+1}/{len(manifest)}',flush=True)
 digest=sha(archive);archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
 archive.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 report={'archive':str(archive),'bytes':archive.stat().st_size,'files':len(manifest),'sha256':digest,'all_files_verified':True}
 (a.output/f'latest-{a.label}-snapshot.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
