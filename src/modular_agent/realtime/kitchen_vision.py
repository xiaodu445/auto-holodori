"""Frozen YOLO click-point adapter; full-client coordinates in/out."""
import os,json,math,hashlib
from pathlib import Path
import cv2,numpy as np
from modular_agent.realtime.kitchen_match import Item,Observation
from modular_agent.realtime.kitchen_ui import HudReader

def select_click_point(bbox,keypoint,other_boxes=()):
    """One geometric candidate per valid box; not a visible-mask guarantee."""
    a,b,c,d=bbox
    if keypoint and len(keypoint)>=2:
        x,y=keypoint[:2];score=keypoint[2] if len(keypoint)>2 else 1
        if all(math.isfinite(v) for v in [x,y,score]) and score>0 and a<=x<c and b<=y<d:return x,y,score,'keypoint'
    options=[]
    for u in [.5,.35,.65,.2,.8]:
        for v in [.5,.35,.65,.2,.8]:
            x=a+(c-a)*u;y=b+(d-b)*v
            covered=sum(q[0]<=x<q[2] and q[1]<=y<q[3] for q in other_boxes)
            options.append((covered,(u-.5)**2+(v-.5)**2,x,y))
    covered,_,x,y=min(options)
    return x,y,0.,'box_fallback_overlap' if covered else 'box_fallback'


class KitchenDetector:
    def __init__(self,weights,device='0',confidence=.25,roi=(.20,.21,.78,.79),tail_confidence=.12):
        root=Path(__file__).resolve().parents[3]
        os.environ.setdefault('YOLO_CONFIG_DIR',str(root/'runtime/kitchen/ultralytics-config'))
        os.environ.setdefault('MPLCONFIGDIR',str(root/'runtime/kitchen/matplotlib-cache'))
        from ultralytics import YOLO
        self.hud=HudReader(root/'data/kitchen/ui-icons')
        self.pt_weights=Path(weights).resolve();self.engine_size=None;selected=self.pt_weights
        profile_path=root/'data/kitchen/runtime-profile.json'
        if profile_path.exists() and str(device).lower()!='cpu':
            config=json.loads(profile_path.read_text(encoding='utf-8')).get('tensorrt',{})
            if config and self.pt_weights==(root/config['source']).resolve() and (root/config['engine']).is_file():
                try:
                    import torch,tensorrt
                    if (torch.cuda.get_device_name(0)==config['gpu'] and tensorrt.__version__==config['tensorrt'] and
                        hashlib.sha256(self.pt_weights.read_bytes()).hexdigest()==config['source_sha256']):
                        selected=root/config['engine'];self.engine_size=config['input_size']
                except (ImportError,RuntimeError,OSError) as error:print('TensorRT不可用，使用PyTorch：'+str(error),flush=True)
        self.model=YOLO(str(selected),task='pose');self.device=device;self.confidence=confidence;self.roi=roi
        self.tail_confidence=min(confidence,tail_confidence) if tail_confidence>0 else confidence
        print('厨房推理后端：'+('TensorRT FP16' if self.engine_size else 'PyTorch'),flush=True)
    def _fallback(self,reason):
        from ultralytics import YOLO
        print('TensorRT回退PyTorch：'+str(reason),flush=True)
        self.model=YOLO(str(self.pt_weights),task='pose');self.engine_size=None
    def _predict_model(self,image,side):
        if self.engine_size and side!=self.engine_size:self._fallback(f'原生输入{side}与引擎{self.engine_size}不同')
        try:return self.model.predict(image,imgsz=side,rect=False,conf=self.tail_confidence,device=self.device,verbose=False)
        except Exception as error:
            if not self.engine_size:raise
            self._fallback(error)
            return self.model.predict(image,imgsz=side,rect=False,conf=self.tail_confidence,device=self.device,verbose=False)
    def warmup(self):
        # Match native padded input; pay CUDA/fusion initialization before countdown.
        self._predict_model(np.zeros((736,736,3),dtype=np.uint8),736)

    def predict(self,image,frame_id,captured,clock,bounds=()):
        h,w=image.shape[:2];x0,y0,x1,y1=[round(v*(w if i%2==0 else h)) for i,v in enumerate(self.roi)]
        crop=image[y0:y1,x0:x1];ch,cw=crop.shape[:2];side=((max(ch,cw)+31)//32)*32;left=(side-cw)//2;top=(side-ch)//2
        padded=cv2.copyMakeBorder(crop,top,side-ch-top,left,side-cw-left,cv2.BORDER_CONSTANT,value=(114,114,114))
        result=self._predict_model(padded,side)[0];items=[]
        boxes=[]
        for box in result.boxes:
            a,b,c,d=box.xyxy[0].cpu().tolist();boxes.append((max(x0,a-left+x0),max(y0,b-top+y0),min(x1,c-left+x0),min(y1,d-top+y0)))
        for i,box in enumerate(result.boxes):
            bbox=boxes[i]
            if not all(math.isfinite(v) for v in bbox) or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]:continue
            kp=None
            if result.keypoints is not None and len(result.keypoints.data)>i:
                raw=result.keypoints.data[i,0].cpu().tolist();kp=[raw[0]-left+x0,raw[1]-top+y0,raw[2] if len(raw)>2 else 1]
            px,py,point_score,source=select_click_point(bbox,kp,[q for j,q in enumerate(boxes) if j!=i])
            items.append(Item(f'{frame_id}:{i}',result.names[int(box.cls.item())],px,py,float(box.conf.item()),bbox,point_score,source))
        tray,targets,details=self.hud.read(image)
        details['tail_confidence']=self.tail_confidence
        details['inference_backend']='tensorrt_fp16' if self.engine_size else 'pytorch'
        return Observation(frame_id,captured,clock(),tuple(items),tuple(bounds),tray=tray,targets=targets,ui_details=details)

class BoardRimGate:
    """Prototype scene-change detector, not a trained popup/HUD classifier.
Only compare the plate rim outside the object ROI; stable menu automation is
intentionally not implemented. Live must be started manually inside a round.
"""
    def __init__(self):self.reference=None;self.recovering=False;self.previous=None;self.stable=0;self.refine=0
    def begin_recovery(self):
        self.reference=None;self.recovering=True;self.previous=None;self.stable=0;self.refine=8
    def check(self,image):
        small=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(160,90))
        mask=np.zeros_like(small,dtype=bool);mask[13:76,27:131]=True;mask[18:72,31:126]=False
        pixels=small[mask].astype(float)
        if self.recovering:
            # Outside central intro cards: test the basket itself, not whole-screen stability.
            gray=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(630,354))
            sharp=[cv2.Laplacian(gray[y:y+35,x:x+40],cv2.CV_64F).var() for y,x in [(100,140),(225,140),(240,280),(100,430),(245,430)]]
            if float(np.median(sharp))<40:return False
            self.recovering=False;self.reference=pixels;return True
        if self.refine>0:
            self.refine-=1;self.reference=pixels;return True
        if self.reference is None:self.reference=pixels;return True
        return float(np.mean(np.abs(pixels-self.reference)))<30

def choose_weights(root):
    root=Path(root)
    profile=root/'data/kitchen/runtime-profile.json'
    if profile.exists():
        data=json.loads(profile.read_text(encoding='utf-8'));weights=(root/data['weights']).resolve()
        if not weights.is_file():raise ValueError('固定模型文件不存在：'+str(weights))
        return weights
    choices=[]
    for p in (Path(root)/'domains/hololive_dreams/models/kitchen/runs').glob('**/progress.json'):
        try:
            state=json.loads(p.read_text(encoding='utf-8'));weights=p.parent/'weights/best.pt'
            if state.get('phase')=='completed' and weights.exists() and state.get('model_size')=='x':choices.append(weights)
        except (OSError,ValueError):pass
    if not choices:raise ValueError('没有已完成的YOLO26x模型，请指定 --weights')
    return max(choices,key=lambda p:p.stat().st_mtime)


class OrderTransitionGate:
    """Cheap fixed-layout Order title + broad colored panel detector per capture."""
    def __init__(self,template):
        self.template=cv2.imread(str(template),cv2.IMREAD_GRAYSCALE)
    def check(self,image):
        if self.template is None:return False
        small=cv2.resize(image,(1260,708))
        # Title is shared across gray, blue and pink recipe pages.
        gray=cv2.cvtColor(small[0:240,250:1010],cv2.COLOR_BGR2GRAY)
        scores=[]
        for scale in [.85,1.,1.15,1.2,1.3]:
            template=cv2.resize(self.template,None,fx=scale,fy=scale)
            scores.append(cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))[1])
        return max(scores)>=.78


class ResultTransitionGate:
    """Recognize the reviewed cooked-dish page title, not the dish illustration."""
    def __init__(self,template):self.template=cv2.imread(str(template),cv2.IMREAD_GRAYSCALE)
    def check(self,image):
        if self.template is None:return False
        small=cv2.resize(image,(1260,708))
        gray=cv2.cvtColor(small[100:280,600:1100],cv2.COLOR_BGR2GRAY)
        return max(cv2.minMaxLoc(cv2.matchTemplate(gray,cv2.resize(self.template,None,fx=s,fy=s),cv2.TM_CCOEFF_NORMED))[1] for s in [.9,1.,1.1])>=.82


def intro_cards_visible(image):
    """Large cream ingredient cards crossing the basket, unlike small top HUD."""
    small=cv2.resize(image,(630,354));b,g,r=cv2.split(small)
    mask=((r>200)&(g>185)&(b>125)&(b<230)&((r.astype(float)-b)>15)).astype('uint8')*255
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cards=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if 55<w<125 and 35<h<90 and 65<y<225:cards.append((x,y,w,h))
    # A row of two or three similarly sized cards, not arbitrary pale food patches.
    return any(abs(a[1]-b[1])<12 and abs(a[3]-b[3])<15 and abs(a[0]-b[0])>45 for i,a in enumerate(cards) for b in cards[i+1:])
