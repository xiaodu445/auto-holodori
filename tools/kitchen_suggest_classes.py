"""Read-only CPU class suggestions; never modifies human annotations."""
import argparse,json,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'learning/kitchen_yolo'))
from prepare import native_square,atomic_json
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'runtime/kitchen/matplotlib-cache'))
import cv2,torch
from ultralytics import YOLO

def main():
    p=argparse.ArgumentParser();p.add_argument('--recording',type=Path,required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--roi',required=True);a=p.parse_args()
    torch.set_num_threads(4)
    cap=cv2.VideoCapture(str(a.recording/'screen.avi'));cap.set(cv2.CAP_PROP_POS_FRAMES,a.index);ok,image=cap.read();cap.release()
    if not ok:raise ValueError('cannot read selected frame')
    h,w=image.shape[:2];roi=json.loads(a.roi);x0,y0,x1,y1=[round(v*(w if i%2==0 else h)) for i,v in enumerate(roi)]
    padded,_,geometry=native_square(image[y0:y1,x0:x1],[])
    model=YOLO(str(a.model));result=model.predict(padded,imgsz=padded.shape[0],rect=False,conf=.05,device='cpu',verbose=False)[0]
    scores={};detections=[]
    for box in result.boxes:
        key=model.names[int(box.cls.item())];score=float(box.conf.item());scores[key]=max(scores.get(key,0),score)
        bx=box.xyxy[0].tolist();bx=[v-geometry['padding_left' if i%2==0 else 'padding_top'] for i,v in enumerate(bx)];bbox=[max(x0,min(x1,bx[0]+x0)),max(y0,min(y1,bx[1]+y0)),max(x0,min(x1,bx[2]+x0)),max(y0,min(y1,bx[3]+y0))]
        if bbox[2]>bbox[0] and bbox[3]>bbox[1]:detections.append(dict(class_id=key,score=score,bbox=bbox))
    atomic_json(a.output,dict(frame=a.index,recording=str(a.recording),model=str(a.model),scores=scores,detections=detections,meaning='maximum retained detection confidence per class, not calibrated class-presence probability'))

if __name__=='__main__':main()
