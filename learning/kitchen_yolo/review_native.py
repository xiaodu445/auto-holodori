"""Native-pixel validation previews for a completed comparison run."""
import argparse,json,os,cv2
from pathlib import Path
import numpy as np
from prepare import ROOT,native_square
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
from ultralytics import YOLO


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--data',type=Path,required=True);args=parser.parse_args()
    snapshot=json.loads((args.data.parent/'label-snapshot.json').read_text(encoding='utf-8'))
    model=YOLO(str(args.run_dir/'weights/best.pt'));out=args.run_dir/'native-review';out.mkdir(exist_ok=True)
    capture=cv2.VideoCapture(str(ROOT/'runtime/kitchen/recordings/20261021-212928-866150/screen.avi'))
    frames={f['video_index']:f for f in snapshot['frames']};reports=[];tiles=[]
    for index in snapshot['val']+[4300]:
        capture.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=capture.read();assert ok
        h,w=image.shape[:2];l,t,r,b=snapshot['roi'];x0,y0,x1,y1=round(l*w),round(t*h),round(r*w),round(b*h)
        roi=image[y0:y1,x0:x1].copy();padded,_,transform=native_square(roi,[]);left,top=transform['padding_left'],transform['padding_top']
        result=model.predict(padded,imgsz=padded.shape[0],rect=False,conf=.25,device=0,verbose=False)[0]
        annotated=roi.copy();rows=[]
        for i,box in enumerate(result.boxes):
            a,b,c,d=box.xyxy[0].cpu().tolist();a-=left;c-=left;b-=top;d-=top
            kp=result.keypoints.data[i,0].cpu().tolist();px,py=kp[0]-left,kp[1]-top
            if not 0<=px<roi.shape[1] or not 0<=py<roi.shape[0]:continue
            key=model.names[int(box.cls.item())];score=float(box.conf.item())
            cv2.rectangle(annotated,(round(a),round(b)),(round(c),round(d)),(0,220,255),2)
            cv2.drawMarker(annotated,(round(px),round(py)),(0,0,255),cv2.MARKER_CROSS,12,2)
            cv2.putText(annotated,f'{key} {score:.2f}',(max(0,round(a)),max(12,round(b)-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),3)
            cv2.putText(annotated,f'{key} {score:.2f}',(max(0,round(a)),max(12,round(b)-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,255),1)
            rows.append(dict(class_id=key,score=score,x=px+x0,y=py+y0,keypoint_score=kp[2]))
        pair=np.concatenate([roi,annotated],axis=1);pair=cv2.copyMakeBorder(pair,35,0,0,0,cv2.BORDER_CONSTANT)
        scope='VAL' if index in snapshot['val'] else 'UNLABELED SAME SESSION'
        cv2.putText(pair,f'{index} | {scope} | native input {padded.shape[0]} | {len(rows)} candidates',(10,24),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),1)
        cv2.imwrite(str(out/f'frame-{index:06d}.jpg'),pair);tiles.append(cv2.resize(pair,(1200,round(pair.shape[0]*1200/pair.shape[1]))))
        reports.append(dict(frame=index,scope=scope,predictions=rows))
    capture.release();cv2.imwrite(str(out/'overview.jpg'),np.concatenate(tiles,axis=0));(out/'predictions.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')


if __name__=='__main__':main()
