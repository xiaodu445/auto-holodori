"""Render trained YOLO click predictions next to original labels; never sends input."""
import argparse,os,json,cv2
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
from ultralytics import YOLO


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,default=ROOT/'learning/kitchen_yolo/runs/medium-progress-20261022');parser.add_argument('--imgsz',type=int,default=960);args=parser.parse_args()
    run=args.run_dir
    snapshot=json.loads((ROOT/'learning/kitchen_yolo/datasets/5d82c7890e09/label-snapshot.json').read_text(encoding='utf-8'))
    frames={f['video_index']:f for f in snapshot['frames']};classes=[c['id'] for c in snapshot['classes']['classes']]
    model=YOLO(str(run/'weights/best.pt'));out=run/'review';out.mkdir(exist_ok=True)
    capture=cv2.VideoCapture(str(ROOT/'runtime/kitchen/recordings/20261021-212928-866150/screen.avi'))
    reports=[];thumbnails=[]
    for index in [1085,2715,4624,3368,4129,2000,4300]:
        capture.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=capture.read();assert ok
        h,w=image.shape[:2];l,t,r,b=snapshot['roi'];x0,y0,x1,y1=round(l*w),round(t*h),round(r*w),round(b*h)
        crop=image[y0:y1,x0:x1].copy();prediction=crop.copy();labels=crop.copy()
        result=model.predict(crop,imgsz=args.imgsz,rect=False,conf=.25,device=0,verbose=False)[0]
        points=[]
        for j,box in enumerate(result.boxes):
            a,b,c,d=box.xyxy[0].cpu().tolist();cls=int(box.cls.item());score=float(box.conf.item())
            name=model.names[cls];cv2.rectangle(prediction,(round(a),round(b)),(round(c),round(d)),(0,180,255),2)
            text=f'{name} {score:.2f}';cv2.putText(prediction,text,(round(a),max(12,round(b)-3)),cv2.FONT_HERSHEY_SIMPLEX,.42,(0,0,0),3)
            cv2.putText(prediction,text,(round(a),max(12,round(b)-3)),cv2.FONT_HERSHEY_SIMPLEX,.42,(0,220,255),1)
            kp=result.keypoints.data[j,0].cpu().tolist();px,py=kp[:2]
            cv2.drawMarker(prediction,(round(px),round(py)),(0,0,255),cv2.MARKER_CROSS,15,2)
            points.append(dict(class_id=name,score=score,bbox=[a+x0,b+y0,c+x0,d+y0],click=[px+x0,py+y0],keypoint_score=kp[2] if len(kp)>2 else None))
        scope='VAL' if index in snapshot['val'] else 'TRAIN' if index in snapshot['train'] else 'UNLABELED SAME SESSION'
        row=frames.get(index)
        if row:
            for p in row['points']:
                a,b,c,d=p['bbox'];a-=x0;c-=x0;b-=y0;d-=y0
                cv2.rectangle(labels,(a,b),(c,d),(0,180,0),1)
                px,py=p['x']-x0,p['y']-y0;cv2.circle(labels,(px,py),4,(0,255,0),2)
                cv2.putText(labels,p['class_id'],(a,max(12,b-3)),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,0,0),3)
                cv2.putText(labels,p['class_id'],(a,max(12,b-3)),cv2.FONT_HERSHEY_SIMPLEX,.38,(0,255,0),1)
        panels=[]
        for im,title in [(labels,f'Frame {index} | {scope} | '+(f'labels={len(row["points"])}' if row else 'no labels')),(prediction,f'YOLO26m | conf>=0.25 | predictions={len(points)}')]:
            im=cv2.copyMakeBorder(im,35,0,0,0,cv2.BORDER_CONSTANT,value=(25,25,25))
            cv2.putText(im,title,(10,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1);panels.append(im)
        pair=np.concatenate(panels,axis=1);cv2.imwrite(str(out/f'frame-{index:06d}.jpg'),pair)
        thumbnails.append(cv2.resize(pair,(1000,round(pair.shape[0]*1000/pair.shape[1]))))
        reports.append(dict(frame=index,scope=scope,labels=len(row['points']) if row else None,predictions=points))
    capture.release();cv2.imwrite(str(out/'overview.jpg'),np.concatenate(thumbnails,axis=0))
    (out/'predictions.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([dict(frame=x['frame'],scope=x['scope'],labels=x['labels'],predictions=len(x['predictions'])) for x in reports],indent=2))


if __name__=='__main__':main()
