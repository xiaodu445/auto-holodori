"""ONNX Runtime CPU inference on images/videos. Never sends mouse input."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np
import onnxruntime as ort


def preprocess(image,config):
    h,w=image.shape[:2];l,t,r,b=config['roi'];box=[round(l*w),round(t*h),round(r*w),round(b*h)]
    x0,y0,x1,y1=box
    image=cv2.resize(image[y0:y1,x0:x1],(config['width'],config['height']))[:,:,::-1].astype(np.float32)/255
    image=(image-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    return np.ascontiguousarray(image.transpose(2,0,1)[None]),box


def decode(outputs,config,box,threshold=.3):
    heat,offset=outputs;heat=1/(1+np.exp(-np.clip(heat[0],-60,60)));offset=offset[0]
    kernel=np.ones((3,3),np.uint8);candidates=[]
    for cls,h in enumerate(heat):
        yy,xx=np.where((h>=cv2.dilate(h,kernel)) & (h>=threshold))
        for y,x in zip(yy,xx):candidates.append((float(h[y,x]),cls,int(x),int(y)))
    candidates.sort(reverse=True);x0,y0,x1,y1=box;result=[]
    for score,cls,x,y in candidates[:150]:
        px=x0+(x+float(offset[0,y,x]))*4*(x1-x0)/config['width']
        py=y0+(y+float(offset[1,y,x]))*4*(y1-y0)/config['height']
        key=config['class_ids'][cls]
        result.append(dict(class_id=key,name=config['classes'][key]['name'],x=px,y=py,score=score))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--model-dir',type=Path,required=True)
    source=p.add_mutually_exclusive_group(required=True);source.add_argument('--image',type=Path);source.add_argument('--video',type=Path)
    p.add_argument('--frame',type=int,default=0);p.add_argument('--threshold',type=float,default=.3)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    config=json.loads((a.model_dir/'config.json').read_text(encoding='utf-8'))
    if a.image:image=cv2.imread(str(a.image))
    else:
        capture=cv2.VideoCapture(str(a.video));capture.set(cv2.CAP_PROP_POS_FRAMES,a.frame);ok,image=capture.read();capture.release()
        if not ok:raise ValueError('cannot decode video frame')
    if image is None:raise ValueError('cannot read input')
    cv2.setNumThreads(1);options=ort.SessionOptions();options.intra_op_num_threads=4
    session=ort.InferenceSession(str(a.model_dir/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    data,box=preprocess(image,config)
    start=time.perf_counter();outputs=session.run(None,{'image':data});elapsed=(time.perf_counter()-start)*1000
    points=decode(outputs,config,box,a.threshold)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.with_suffix('.json').write_text(json.dumps(dict(candidates=points,first_inference_ms=elapsed,roi_pixels=box,
        coordinate_system='full_input_image_pixels',sends_input=False,notes='Scores are uncalibrated; not a click-success probability.'),ensure_ascii=False,indent=2),encoding='utf-8')
    for point in points:
        x,y=round(point['x']),round(point['y']);cv2.circle(image,(x,y),5,(0,255,0),2)
        cv2.putText(image,f'{point["class_id"]} {point["score"]:.2f}',(x+6,y-4),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,0),1)
    if not cv2.imwrite(str(a.output.with_suffix('.jpg')),image):raise RuntimeError('image write failed')
    print(json.dumps(dict(candidates=len(points),output=str(a.output.with_suffix('.jpg')))))


if __name__=='__main__':main()
