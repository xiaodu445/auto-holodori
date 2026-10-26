"""Evaluate old/new models on identical frozen grouped validation images."""
import os,json,cv2,numpy as np
import argparse
from pathlib import Path
from prepare import ROOT,atomic_json
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'runtime/kitchen/matplotlib-cache'))
from ultralytics import YOLO

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=ROOT/'learning/kitchen_yolo/datasets/combined-16b1df2afd68/data.yaml');parser.add_argument('--run',type=Path,default=ROOT/'learning/kitchen_yolo/runs/x-combined-20261022-161146');parser.add_argument('--old',type=Path,default=ROOT/'learning/kitchen_yolo/runs/native-comparison-20261022/xlarge-native/weights/best.pt');args=parser.parse_args()
    data=args.data
    snapshot=json.loads((data.parent/'label-snapshot.json').read_text(encoding='utf-8'))
    run=args.run;out=run/'comparison-review';out.mkdir(exist_ok=True)
    models=[YOLO(str(args.old)),YOLO(str(run/'weights/best.pt'))]
    assert all(models[1].names[k]==v for k,v in models[0].names.items()),'class order changed'
    reports=[]
    for title,model in zip(['old','new'],models):
        metrics=model.val(data=str(data),imgsz=736,batch=2,device=0,workers=0,plots=False,project=str(out),name=title,verbose=False)
        reports.append(dict(model=title,metrics={k:float(v) for k,v in metrics.results_dict.items()},classes=[dict(class_id=model.names[int(cls)],ap50=float(metrics.box.ap50[i]),recall=float(metrics.box.r[i])) for i,cls in enumerate(metrics.box.ap_class_index)]))
    atomic_json(out/'same-validation-metrics.json',reports)
    tiles=[]
    for e in snapshot['entries']:
        if e['split']!='val':continue
        f=e['frame'];name=e['recording']+'-'+str(f['video_index']);padded=cv2.imread(str(data.parent/'images/val'/(name+'.png')))
        tr=snapshot['transforms'][name];left,top=tr['padding_left'],tr['padding_top'];w,h=tr['original_roi_size'];roi=padded[top:top+h,left:left+w].copy();panels=[roi];counts=[]
        for model in models:
            r=model.predict(padded,imgsz=736,rect=False,conf=.25,device=0,verbose=False)[0];canvas=roi.copy();count=0
            for i,box in enumerate(r.boxes):
                px,py=r.keypoints.data[i,0,:2].cpu().tolist();px-=left;py-=top
                if not(0<=px<w and 0<=py<h):continue
                a,b,c,d=box.xyxy[0].cpu().tolist();a-=left;c-=left;b-=top;d-=top
                cls=model.names[int(box.cls.item())];score=float(box.conf.item());count+=1
                cv2.rectangle(canvas,(round(a),round(b)),(round(c),round(d)),(0,220,255),1)
                cv2.drawMarker(canvas,(round(px),round(py)),(0,0,255),cv2.MARKER_CROSS,10,2)
                text=f'{cls} {score:.2f}';pos=(max(0,round(a)),max(12,round(b)-3))
                cv2.putText(canvas,text,pos,cv2.FONT_HERSHEY_SIMPLEX,.37,(0,0,0),2);cv2.putText(canvas,text,pos,cv2.FONT_HERSHEY_SIMPLEX,.37,(0,255,255),1)
            counts.append(count);panels.append(canvas)
        row=np.concatenate(panels,axis=1);row=cv2.copyMakeBorder(row,30,0,0,0,cv2.BORDER_CONSTANT)
        for j,label in enumerate([f'ORIGINAL | {f["video_index"]} | labels {len(f["points"])}',f'OLD | {counts[0]} predictions',f'NEW | {counts[1]} predictions']):cv2.putText(row,label,(j*w+8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        cv2.imwrite(str(out/(name+'.jpg')),row)
        if f['video_index'] in [1085,4624,384]:tiles.append(cv2.resize(row,(1800,round(row.shape[0]*1800/row.shape[1]))))
    cv2.imwrite(str(out/'overview.jpg'),np.concatenate(tiles,axis=0));print(json.dumps(reports),flush=True)

if __name__=='__main__':main()
