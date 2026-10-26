"""Native ROI preprocessing for a model trained with native-padding data."""
import argparse,json,os
from pathlib import Path
import cv2
from prepare import ROOT,native_square
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))


def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',type=Path,required=True);p.add_argument('--image',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--conf',type=float,default=.25);a=p.parse_args()
    from ultralytics import YOLO
    image=cv2.imread(str(a.image))
    if image is None:raise ValueError('cannot load input')
    h,w=image.shape[:2];x0,y0,x1,y1=[round(v*s) for v,s in zip([.20,.21,.78,.79],[w,h,w,h])]
    padded,_,transform=native_square(image[y0:y1,x0:x1],[])
    result=YOLO(str(a.weights)).predict(padded,imgsz=padded.shape[0],rect=False,conf=a.conf,verbose=False)[0]
    rows=[];left,top=transform['padding_left'],transform['padding_top']
    for i,box in enumerate(result.boxes):
        px,py,score=result.keypoints.data[i,0].cpu().tolist()
        px-=left;py-=top
        if not 0<=px<x1-x0 or not 0<=py<y1-y0:continue
        bounds=box.xyxy[0].cpu().tolist()
        rows.append(dict(class_id=result.names[int(box.cls.item())],score=float(box.conf.item()),point_score=score,
            x=px+x0,y=py+y0,bbox=[bounds[0]-left+x0,bounds[1]-top+y0,bounds[2]-left+x0,bounds[3]-top+y0]))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(dict(transform=transform,candidates=rows,sends_input=False),indent=2),encoding='utf-8')


if __name__=='__main__':main()
