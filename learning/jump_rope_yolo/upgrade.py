"""Preserved upgrade entry point. Never activates newly trained/exported assets automatically."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
CURRENT=HERE/'runs/temporal-history-07-late/weights/last.pt'
DATA=HERE/'datasets/temporal-trial-07'
EXACT=ROOT/'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames'
def check():
 manifest=json.loads((DATA/'MANIFEST.json').read_text(encoding='utf-8'))
 frames={r['frame'] for r in manifest['frames']}|{f for r in manifest['frames'] for f in r['history_frames']}
 missing=[str(EXACT/f'{f:06d}.jpg') for f in sorted(frames) if not (EXACT/f'{f:06d}.jpg').is_file()]
 if not CURRENT.is_file():missing.append(str(CURRENT))
 for r in manifest['frames']:
  for path in [DATA/f"labels/{r['split']}/{r['frame']:06d}.txt",*[DATA/f"masks/{kind}/{r['frame']:06d}.png" for kind in ('full','visible','occluded')]]:
   if not path.is_file():missing.append(str(path))
 print(json.dumps({'source_weights':str(CURRENT),'training_dataset':str(DATA),'raw_frames':len(frames),'missing':missing},ensure_ascii=False,indent=2))
 if missing:raise SystemExit('Upgrade inputs missing; restore from backup before training.')
 return True
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['check','train','export','templates']);p.add_argument('--name');p.add_argument('--epochs',type=int,default=30);p.add_argument('--batch',type=int,default=4);p.add_argument('--weights',type=Path,default=CURRENT);p.add_argument('--prior-weights',type=Path,default=CURRENT);a=p.parse_args()
 if a.action=='check':check();return
 if a.action=='templates':subprocess.run([sys.executable,str(HERE/'compile_stage5_trial.py')],check=True);return
 if not a.name or not a.name.replace('-','').isalnum():p.error('--name is required, letters/digits/hyphens only; use a new version name')
 if a.action=='train':
  check()
  print('Fine-tuning current07 with explicitly selected predicted-history teacher; this does not recreate the original control05 experiment.',flush=True)
  subprocess.run([sys.executable,str(HERE/'run_temporal_trial.py'),'--dataset',str(DATA),'--name',a.name,'--history-only','--continuity-loss','--epochs',str(a.epochs),'--batch',str(a.batch),'--initial-weights',str(a.weights),'--prior-weights',str(a.prior_weights)],check=True)
 else:
  import shutil,time
  import torch,tensorrt
  from ultralytics import YOLO
  folder=HERE/'engines'/a.name
  if folder.exists():raise FileExistsError('Use a new engine name; current engine stays preserved.')
  if not a.weights.is_file():raise FileNotFoundError(a.weights)
  folder.mkdir();copied=folder/(a.name+'.pt');shutil.copyfile(a.weights,copied)
  digest=hashlib.sha256(a.weights.read_bytes()).hexdigest();start=time.perf_counter()
  result=YOLO(copied).export(format='engine',imgsz=960,batch=1,device=0,quantize=16,dynamic=False,workspace=1,simplify=True,opset=18,nms=None)
  with Path(result).open('rb') as f:metadata=json.loads(f.read(int.from_bytes(f.read(4),'little')))
  if metadata.get('end2end') is not False:raise RuntimeError('Unexpected detection branch; do not activate this engine')
  (folder/'export.json').write_text(json.dumps({'source':str(a.weights),'sha256':digest,'engine':str(result),'seconds':time.perf_counter()-start,'torch':torch.__version__,'tensorrt':tensorrt.__version__,'activated':False},indent=2),encoding='utf-8')
if __name__=='__main__':main()
