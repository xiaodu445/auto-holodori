"""Offline equal-input parity and timing; no capture or game input."""
import os,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ['YOLO_CONFIG_DIR']=str(ROOT/'learning/kitchen_points/ultralytics-config');os.environ['MPLCONFIGDIR']=str(ROOT/'runtime/kitchen/matplotlib-cache')
import cv2,numpy as np,torch
from ultralytics import YOLO
cv2.setNumThreads(1);torch.set_num_threads(4)
folder=ROOT/'learning/kitchen_yolo/engines/confusions-20261024-736-fp16';export=json.loads((folder/'export.json').read_text());dataset=ROOT/'learning/kitchen_yolo/datasets/combined-0d6b063772c5'
paths=list(sorted((dataset/'images/val').glob('*.png')))+list(sorted((dataset/'images/train').glob('*.png')))[::4]
images=[cv2.imread(str(p)) for p in paths]
models=[YOLO(str(ROOT/export['source']),task='pose'),YOLO(str(ROOT/export['engine']),task='pose')]
def predict(model,image):return model.predict(image,imgsz=736,rect=False,conf=.25,device=0,verbose=False)[0]
def stats(values):return dict(p50_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)))
results=[];timings=[]
for model in models:
 for _ in range(15):predict(model,images[0])
 values=[];stage=[]
 for i in range(60):
  torch.cuda.synchronize();start=time.perf_counter();r=predict(model,images[i%len(images)]);torch.cuda.synchronize();values.append((time.perf_counter()-start)*1000);stage.append(r.speed['inference'])
 timings.append(dict(total_call=stats(values),inference=stats(stage)))
 results.append([predict(model,image) for image in images])
def iou(a,b):
 inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]));return inter/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)
rows=[];distances=[];scores=[];matched=0;total_pt=0;total_trt=0
for path,a,b in zip(paths,*results):
 aa=a.boxes.data.cpu().numpy();bb=b.boxes.data.cpu().numpy();used=set();pairs=[]
 for i,x in enumerate(aa):
  candidates=[(iou(x,y),j) for j,y in enumerate(bb) if j not in used and int(x[5])==int(y[5])]
  if not candidates:continue
  overlap,j=max(candidates)
  if overlap<.5:continue
  used.add(j);pairs.append((i,j));scores.append(abs(float(x[4])-float(bb[j][4])))
  distances.append(float(np.linalg.norm(a.keypoints.xy[i,0].cpu().numpy()-b.keypoints.xy[j,0].cpu().numpy())))
 matched+=len(pairs);total_pt+=len(aa);total_trt+=len(bb)
 rows.append(dict(image=str(path.relative_to(ROOT)),pt=len(aa),trt=len(bb),matched=len(pairs)))
report=dict(gpu=torch.cuda.get_device_name(0),input_size=736,images=len(images),timing_scope='batch1 same cached native padded images; 15 warmups,60 measured; synchronized Python predict incl pre/post; excludes capture/HUD/mouse/waits',pytorch=timings[0],tensorrt_fp16=timings[1],pt_detections=total_pt,trt_detections=total_trt,matched_same_class_iou50=matched,matched_keypoint_distance_px=stats(distances) if distances else None,max_score_delta=max(scores,default=0),frames=rows)
# Distances are pixels, not milliseconds.
if report['matched_keypoint_distance_px']:report['matched_keypoint_distance_px']={'p50':float(np.median(distances)),'p95':float(np.percentile(distances,95)),'max':max(distances)}
(folder/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='frames'}),flush=True)
