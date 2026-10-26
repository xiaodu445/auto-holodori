"""Batch-one GPU inference timings, excluding live capture and input."""
import argparse,json,os,time
from pathlib import Path
import cv2,numpy as np,torch
ROOT=Path(__file__).resolve().parents[2]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
from ultralytics import YOLO


def benchmark(path,image,size,half=False):
    model=YOLO(str(path),task='pose');values=[];parts={k:[] for k in ['preprocess','inference','postprocess']}
    for i in range(80):
        torch.cuda.synchronize();start=time.perf_counter()
        result=model.predict(image,imgsz=size,rect=False,conf=.25,device=0,quantize=16 if half else None,verbose=False)[0]
        torch.cuda.synchronize();elapsed=(time.perf_counter()-start)*1000
        if i>=20:
            values.append(elapsed)
            for k in parts:parts[k].append(result.speed[k])
    def stats(v):return dict(p50_ms=round(float(np.median(v)),3),p95_ms=round(float(np.percentile(v,95)),3))
    return dict(model=str(path),size=size,half_requested=half,warmup=20,measurements=60,call_total=stats(values),stages={k:stats(v) for k,v in parts.items()})


def main():
    p=argparse.ArgumentParser();p.add_argument('--export-trt',action='store_true');a=p.parse_args()
    run=ROOT/'learning/kitchen_yolo/runs/diagnostic-updates-20261022';out=run/'benchmark';out.mkdir(exist_ok=True)
    capture=cv2.VideoCapture(str(ROOT/'runtime/kitchen/recordings/20261021-212928-866150/screen.avi'));capture.set(cv2.CAP_PROP_POS_FRAMES,4300);ok,image=capture.read();capture.release();assert ok
    image=image[149:559,252:981].copy();cv2.setNumThreads(1);torch.set_num_threads(4)
    rows=[];pt=run/'weights/best.pt'
    for size,half in [(640,False),(640,True),(960,True)]:
        row=benchmark(pt,image,size,half);rows.append(row);print(json.dumps(row),flush=True)
    engine=run/'weights/best.engine'
    if a.export_trt or engine.exists():
        if not engine.exists():
            model=YOLO(str(pt));engine=Path(model.export(format='engine',imgsz=640,quantize=16,device=0,workspace=1,dynamic=False,nms=False,simplify=False))
        row=benchmark(engine,image,640,True);rows.append(row);print(json.dumps(row),flush=True)
    report=dict(gpu=torch.cuda.get_device_name(0),batch=1,results=rows,scope='single cached real ROI; excludes capture/mouse/waits, total includes Python API and pre/postprocessing; not a multi-image or live-game benchmark')
    (out/'inference-timing.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
