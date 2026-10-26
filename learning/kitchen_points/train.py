"""Small point detector: fit diagnostic, not independent validation."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import time

import cv2
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from torchvision.models import mobilenet_v3_small


class PointNet(nn.Module):
    def __init__(self,classes,weights=None):
        super().__init__()
        source=mobilenet_v3_small(weights=None)
        if weights:source.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True))
        self.backbone=nn.Sequential(*list(source.features.children())[:9])
        self.lateral=nn.ModuleList(nn.Conv2d(c,64,1) for c in [16,24,48])
        self.fuse=nn.Sequential(nn.Conv2d(64,64,3,padding=1,groups=64),nn.Conv2d(64,64,1),nn.ReLU())
        self.heatmap=nn.Sequential(nn.Conv2d(64,64,3,padding=1),nn.ReLU(),nn.Conv2d(64,classes,1))
        self.offset=nn.Sequential(nn.Conv2d(64,32,3,padding=1),nn.ReLU(),nn.Conv2d(32,2,1))
        nn.init.constant_(self.heatmap[-1].bias,-2.19)

    def forward(self,x):
        features=[]
        for i,layer in enumerate(self.backbone):
            x=layer(x)
            if i in [1,3,8]:features.append(x)
        a,b,c=[layer(x) for layer,x in zip(self.lateral,features)]
        b=b+F.interpolate(c,size=b.shape[-2:],mode='nearest')
        a=self.fuse(a+F.interpolate(b,size=a.shape[-2:],mode='nearest'))
        return self.heatmap(a),self.offset(a).sigmoid()


def targets(points,ignored,classes,width,height,stride=4):
    ow,oh=width//stride,height//stride
    heat=np.zeros((classes,oh,ow),np.float32);offset=np.zeros((2,oh,ow),np.float32)
    positive=np.zeros((1,oh,ow),np.float32);valid=np.ones((1,oh,ow),np.float32)
    for x0,y0,x1,y1 in ignored:
        valid[:,max(0,int(y0//stride)):min(oh,math.ceil(y1/stride)),max(0,int(x0//stride)):min(ow,math.ceil(x1/stride))]=0
    cells=set()
    yy,xx=np.mgrid[-4:5,-4:5];gaussian=np.exp(-(xx**2+yy**2)/(2*1.3**2)).astype(np.float32)
    for cls,x,y in points:
        fx,fy=x/stride,y/stride;gx,gy=int(fx),int(fy)
        if not 0<=gx<ow or not 0<=gy<oh:raise ValueError('point outside input')
        if (gx,gy) in cells:raise ValueError('two labels share output cell; increase resolution')
        cells.add((gx,gy));x0,x1=max(0,gx-4),min(ow,gx+5);y0,y1=max(0,gy-4),min(oh,gy+5)
        np.maximum(heat[cls,y0:y1,x0:x1],gaussian[y0-gy+4:y1-gy+4,x0-gx+4:x1-gx+4],out=heat[cls,y0:y1,x0:x1])
        offset[:,gy,gx]=[fx-gx,fy-gy];positive[:,gy,gx]=1;valid[:,gy,gx]=1
    return heat,offset,positive,valid


def losses(pred,off,heat,target_off,positive,valid):
    probability=pred.sigmoid().clamp(1e-5,1-1e-5)
    pos=(heat==1).float();neg=(heat<1).float()
    number=pos.sum().clamp_min(1)
    hm=-(pos*(1-probability).pow(2)*probability.log()+neg*(1-heat).pow(4)*probability.pow(2)*(1-probability).log())
    hm=(hm*valid).sum()/number
    reg=(F.smooth_l1_loss(off,target_off,reduction='none')*positive).sum()/(positive.sum().clamp_min(1)*2)
    return hm+reg,hm,reg


def load_samples(manifest,width,height,class_ids):
    root=Path(manifest).parent;data=json.loads(Path(manifest).read_text(encoding='utf-8'))
    samples=[];index={key:i for i,key in enumerate(class_ids)}
    for row in data['frames']:
        if not row['complete']:raise ValueError('incomplete label frame')
        image=cv2.imread(str(root/row['image']))
        if image is None:raise ValueError('missing image')
        h,w=image.shape[:2];l,t,r,b=data['roi'];box=[round(l*w),round(t*h),round(r*w),round(b*h)]
        x0,y0,x1,y1=box;sx,sy=width/(x1-x0),height/(y1-y0)
        points=[]
        for p in row['points']:
            if not x0<=p['x']<x1 or not y0<=p['y']<y1:raise ValueError('label outside ROI')
            points.append([index[p['class_id']],(p['x']-x0)*sx,(p['y']-y0)*sy])
        ignored=[[(a-x0)*sx,(b-y0)*sy,(c-x0)*sx,(d-y0)*sy] for a,b,c,d in row['ignore_regions']]
        resized=cv2.resize(image[y0:y1,x0:x1],(width,height))[:,:,::-1].copy()
        x=torch.from_numpy(resized.transpose(2,0,1)).float()/255
        x=(x-torch.tensor([.485,.456,.406])[:,None,None])/torch.tensor([.229,.224,.225])[:,None,None]
        target=targets(points,ignored,len(class_ids),width,height)
        samples.append(dict(x=x,targets=[torch.from_numpy(a) for a in target],row=row,box=box,points=points))
    return data,samples


def decode(logits,offset,threshold=.3):
    prob=logits.sigmoid();peaks=prob*(prob==F.max_pool2d(prob,3,stride=1,padding=1))
    values,indices=peaks.flatten().topk(min(150,peaks.numel()))
    _,height,width=peaks.shape
    result=[]
    for score,idx in zip(values.tolist(),indices.tolist()):
        if score<threshold:break
        cls=idx//(height*width);cell=idx%(height*width);y,x=divmod(cell,width)
        dx,dy=offset[:,y,x].tolist();result.append(dict(class_index=cls,x=(x+dx)*4,y=(y+dy)*4,score=score))
    return result


@torch.inference_mode()
def evaluate(model,samples,device,width,height,threshold=.3):
    model.eval();matched=predicted=truth=0;details=[]
    for sample in samples:
        heat,offset=model(sample['x'][None].to(device));preds=decode(heat[0],offset[0],threshold)
        row=sample['row'];x0,y0,x1,y1=sample['box'];used=set();converted=[]
        for p in preds:
            x=x0+p['x']*(x1-x0)/width;y=y0+p['y']*(y1-y0)/height
            cls=p['class_index'];possibles=[(math.hypot(x-q['x'],y-q['y']),i) for i,q in enumerate(row['points']) if i not in used and sample['points'][i][0]==cls]
            hit=False
            if possibles:
                distance,i=min(possibles)
                if distance<=12:used.add(i);matched+=1;hit=True
            converted.append(dict(class_index=cls,x=x,y=y,score=p['score'],matched_training_point=hit))
        predicted+=len(preds);truth+=len(row['points'])
        details.append(dict(video_index=row['video_index'],predictions=converted))
    return dict(scope='TRAINING_SET_FIT_ONLY',threshold=threshold,matching_radius_original_pixels=12,
                matched=matched,predictions=predicted,labels=truth,precision=matched/max(1,predicted),recall=matched/max(1,truth),frames=details)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--weights',type=Path)
    parser.add_argument('--epochs',type=int,default=300);parser.add_argument('--batch',type=int,default=4)
    parser.add_argument('--width',type=int,default=640);parser.add_argument('--height',type=int,default=352)
    parser.add_argument('--seed',type=int,default=17);args=parser.parse_args()
    if args.width%32 or args.height%32:parser.error('dimensions must be multiples of32')
    args.output.mkdir(parents=True,exist_ok=False)
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed);torch.set_num_threads(4);cv2.setNumThreads(1)
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    data=json.loads(args.manifest.read_text(encoding='utf-8'));class_ids=list(data['classes'])
    data,samples=load_samples(args.manifest,args.width,args.height,class_ids)
    model=PointNet(len(class_ids),args.weights).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.0001)
    schedule=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.epochs,eta_min=.00003)
    tensors=[torch.stack([s['x'] for s in samples]).to(device)]+[torch.stack([s['targets'][j] for s in samples]).to(device) for j in range(4)]
    config=dict(architecture='MobileNetV3Small_stride4_FPN64_point_head',classes=data['classes'],class_ids=class_ids,
        width=args.width,height=args.height,roi=data['roi'],epochs=args.epochs,batch=args.batch,seed=args.seed,
        pretrained=str(args.weights) if args.weights else None,device=str(device),gpu=torch.cuda.get_device_name(0) if device.type=='cuda' else None,
        frames=len(samples),points=sum(len(s['points']) for s in samples),parameters=sum(p.numel() for p in model.parameters()),
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),evaluation='training fit diagnostic; no independent validation',augmentation='none: first fit diagnostic')
    (args.output/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    # Immutable training snapshot; GUI changes do not alter this run.
    (args.output/'manifest-snapshot.json').write_bytes(args.manifest.read_bytes())
    print(json.dumps(config,ensure_ascii=False),flush=True)
    best=float('inf');start=time.perf_counter()
    try:
        for epoch in range(1,args.epochs+1):
            model.train()
            for layer in model.modules():
                if isinstance(layer,nn.BatchNorm2d):layer.eval()
            order=torch.randperm(len(samples),device=device);total=0
            for offset in range(0,len(samples),args.batch):
                idx=order[offset:offset+args.batch];x,heat,off,positive,valid=[t[idx] for t in tensors]
                optimizer.zero_grad(set_to_none=True);pred,offsets=model(x)
                loss,hm,reg=losses(pred,offsets,heat,off,positive,valid)
                if not torch.isfinite(loss):raise RuntimeError('nonfinite loss')
                loss.backward();nn.utils.clip_grad_norm_(model.parameters(),10);optimizer.step();total+=loss.item()*len(idx)
            schedule.step();average=total/len(samples)
            row=dict(epoch=epoch,loss=average,elapsed_seconds=time.perf_counter()-start)
            with (args.output/'history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
            if average<best:
                best=average;torch.save(dict(state_dict=model.state_dict(),config=config,epoch=epoch,loss=average),args.output/'best.pt')
            if epoch==1 or epoch%10==0:print(json.dumps(row),flush=True)
            if epoch%50==0:
                fit=evaluate(model,samples,device,args.width,args.height)
                print(json.dumps({k:v for k,v in fit.items() if k!='frames'}),flush=True)
        model.load_state_dict(torch.load(args.output/'best.pt',map_location=device,weights_only=False)['state_dict']);model.eval()
        fit=evaluate(model,samples,device,args.width,args.height)
        (args.output/'training-fit.json').write_text(json.dumps(fit,indent=2),encoding='utf-8')
        for sample,detail in zip(samples,fit['frames']):
            im=cv2.imread(str(args.manifest.parent/sample['row']['image']))
            for p in detail['predictions']:
                x,y=round(p['x']),round(p['y']);color=(0,255,0) if p['matched_training_point'] else (0,0,255)
                cv2.circle(im,(x,y),5,color,2);cv2.putText(im,class_ids[p['class_index']],(x+5,y-5),cv2.FONT_HERSHEY_SIMPLEX,.4,color,1)
            cv2.imwrite(str(args.output/f'fit-{detail["video_index"]:06d}.jpg'),im)
        cpu=model.cpu();dummy=torch.zeros(1,3,args.height,args.width)
        torch.onnx.export(cpu,dummy,str(args.output/'model.onnx'),input_names=['image'],output_names=['heatmap_logits','offset'],opset_version=17,dynamo=False)
        import onnxruntime as ort
        session=ort.InferenceSession(str(args.output/'model.onnx'),providers=['CPUExecutionProvider'])
        with torch.no_grad():expected=cpu(dummy)
        actual=session.run(None,{'image':dummy.numpy()})
        parity=max(float(np.max(np.abs(a-b.numpy()))) for a,b in zip(actual,expected))
        if parity>.001:raise RuntimeError(f'ONNX parity failed: {parity}')
        summary=dict(status='completed',best_loss=best,elapsed_seconds=time.perf_counter()-start,onnx_max_abs_error=parity,training_fit={k:v for k,v in fit.items() if k!='frames'},generalization='NOT_EVALUATED',click_success='NOT_EVALUATED')
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary),flush=True)
    except KeyboardInterrupt:
        torch.save(dict(state_dict=model.state_dict(),config=config),args.output/'interrupted.pt');raise


if __name__=='__main__':main()
