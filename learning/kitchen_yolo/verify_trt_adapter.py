import os,sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'));os.environ['MPLCONFIGDIR']=str(ROOT/'runtime/kitchen/matplotlib-cache')
import cv2,numpy as np,torch
from dataclasses import replace
from modular_agent.realtime.kitchen_vision import KitchenDetector,choose_weights
from modular_agent.realtime.kitchen_match import plan,Settings
cv2.setNumThreads(1);torch.set_num_threads(4)
paths=list(sorted((ROOT/'data/kitchen/review-archive').glob('*/*/frame.png')))[::3][:12]
images=[cv2.imread(str(p)) for p in paths];weights=choose_weights(ROOT)
a=KitchenDetector(weights);a._fallback('offline timing baseline');b=KitchenDetector(weights)
output=[];observations=[]
for d in [a,b]:
 d.warmup()
 for i in range(3):d.predict(images[0],i,0,lambda:0)
 timings=[];obs=[]
 for rep in range(3):
  for i,image in enumerate(images):
   torch.cuda.synchronize();start=time.perf_counter();o=d.predict(image,i,0,lambda:0);torch.cuda.synchronize();timings.append((time.perf_counter()-start)*1000)
   if rep==0:obs.append(o)
 output.append(dict(backend='tensorrt_fp16' if d.engine_size else 'pytorch',p50_ms=float(np.median(timings)),p95_ms=float(np.percentile(timings,95))))
 observations.append(obs)
rows=[]
for p,x,y in zip(paths,*observations):
 px=plan(replace(x,tray=('',)*7),set(),Settings(confidence=.25),0);py=plan(replace(y,tray=('',)*7),set(),Settings(confidence=.25),0)
 rows.append(dict(image=str(p.relative_to(ROOT)),pt_items=len(x.items),trt_items=len(y.items),same_planned_class_sequence=[a.class_id for a in px]==[a.class_id for a in py]))
report=dict(scope='full KitchenDetector including native ROI/padding, model, point extraction, HUD; archived full-client screenshots; no game input/capture/waits',results=output,frames=rows)
(ROOT/'learning/kitchen_yolo/engines/confusions-20261024-736-fp16/adapter-comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
