"""Fixed HUD icon recognition, separate from board detection.
Uses a human-reviewed local icon bank; unknown is never an empty tray slot.
"""
import json
from collections import Counter
from pathlib import Path
import cv2,numpy as np

TRAY_RECTS=tuple((.224+i*.0815,.879,.282+i*.0815,.965) for i in range(7))
TARGET_RECTS=tuple((x,.075,x+.06,.168) for x in [.369,.459,.549])

def crop_rect(image,rect):
    h,w=image.shape[:2];a,b,c,d=rect
    return image[round(b*h):round(d*h),round(a*w):round(c*w)].copy()

def matches_empty_slot(small,refs):
    # A pale ingredient can have a low whole-patch MAE. Check the interior too.
    for ref in refs:
        if float(np.mean(np.abs(small-ref)))>=8:continue
        delta=(small-ref)[4:28,4:28]
        # Remove uniform lighting changes, preserving ingredient texture and shape.
        delta=delta-np.median(delta,axis=(0,1))
        if float(np.mean(np.abs(delta)))<3.5:return True
    return False


def descriptor(image):
    if image.size==0:return None
    image=cv2.resize(image,(64,64));pixels=image.astype(float)
    edge=np.concatenate([pixels[:3].reshape(-1,3),pixels[-3:].reshape(-1,3),pixels[:, :3].reshape(-1,3),pixels[:,-3:].reshape(-1,3)])
    bg=np.median(edge,axis=0);mask=(np.linalg.norm(pixels-bg,axis=2)>32).astype(np.uint8)
    mask[:2]=0;mask[-2:]=0;mask[:,:2]=0;mask[:,-2:]=0
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
    if count<2:return None
    index=1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA]));x,y,w,h,area=stats[index]
    if area<55:return None
    obj=image[y:y+h,x:x+w];ms=(labels[y:y+h,x:x+w]==index).astype(np.uint8)
    side=48;scale=42/max(w,h);nw,nh=max(1,round(w*scale)),max(1,round(h*scale));left,top=(side-nw)//2,(side-nh)//2
    gray=cv2.cvtColor(obj,cv2.COLOR_BGR2GRAY);gray=cv2.equalizeHist(gray)
    canvas=np.zeros((side,side),np.uint8);sil=np.zeros_like(canvas)
    canvas[top:top+nh,left:left+nw]=cv2.resize(gray,(nw,nh));sil[top:top+nh,left:left+nw]=cv2.resize(ms*255,(nw,nh))
    canvas[sil<50]=0
    gy,gx=np.gradient(canvas.astype(float));magnitude=np.hypot(gx,gy);angles=((np.arctan2(gy,gx)%np.pi)*9/np.pi).astype(int)%9
    hog=np.concatenate([np.bincount(angles[y:y+8,x:x+8].ravel(),weights=magnitude[y:y+8,x:x+8].ravel(),minlength=9) for y in range(0,48,8) for x in range(0,48,8)]).astype(np.float32);hog/=np.linalg.norm(hog)+1e-8
    texture=canvas.astype(np.float32).ravel();texture/=np.linalg.norm(texture)+1e-8
    silhouette=sil.astype(np.float32).ravel()/255;silhouette/=np.linalg.norm(silhouette)+1e-8
    return np.concatenate([hog*np.sqrt(.4),texture*np.sqrt(.35),silhouette*np.sqrt(.25)])

class HudReader:
    def __init__(self,bank):
        bank=Path(bank);meta=json.loads((bank/'index.json').read_text(encoding='utf-8'));features=[];labels=[];self.tray_patterns=[]
        for entry in meta['icons']:
            image=cv2.imread(str(bank/entry['file']));feature=descriptor(image) if image is not None else None
            if feature is not None:features.append(feature);labels.append(entry['class_id'])
            if image is not None and entry.get('region')=='tray':
                pattern=cv2.cvtColor(cv2.resize(image,(64,64)),cv2.COLOR_BGR2GRAY)[10:54,10:54].copy()
                if float(pattern.std())>=10:self.tray_patterns.append((entry['class_id'],pattern))
        self.empties=[cv2.resize(cv2.imread(str(bank/file)),(32,32)).astype(float) for file in meta.get('empty_icons',[])]
        self.features=np.array(features);self.labels=labels;self.previous=None;self.streak=[0]*7;self.use_tray_vision=True
    def classify(self,patch):
        feature=descriptor(patch)
        if feature is None:return None,0.,0.
        values=self.features@feature;scores={}
        for label,value in zip(self.labels,values):scores[label]=max(scores.get(label,-1),float(value))
        ranked=sorted(scores.items(),key=lambda x:-x[1])
        if not ranked:return None,0.,0.
        key,score=ranked[0];margin=score-ranked[1][1] if len(ranked)>1 else score
        return key,score,margin
    def classify_tray(self,patch):
        primary=self.classify(patch)
        if primary[0] and primary[1]>=.78 and primary[2]>=.025:return primary
        # Fixed-slot texture matching avoids unstable connected-component segmentation.
        gray=cv2.cvtColor(cv2.resize(patch,(64,64)),cv2.COLOR_BGR2GRAY)
        scores={}
        for key,pattern in self.tray_patterns:
            score=float(cv2.minMaxLoc(cv2.matchTemplate(gray,pattern,cv2.TM_CCOEFF_NORMED))[1])
            scores[key]=max(scores.get(key,-1),score)
        ranked=sorted(scores.items(),key=lambda row:-row[1])
        if ranked:
            key,score=ranked[0];margin=score-ranked[1][1] if len(ranked)>1 else score
            if score>=.92 and margin>=.08:return key,score,margin
        return primary

    def read_order(self,image):
        """Locate large cream ingredient cards; classify icons without numbers."""
        h,w=image.shape[:2];b,g,r=cv2.split(image)
        mask=((r>200)&(g>185)&(b>125)&(b<230)&((r.astype(float)-b)>15)).astype('uint8')*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cards=[]
        for contour in contours:
            x,y,cw,ch=cv2.boundingRect(contour)
            if .10*w<cw<.19*w and .12*h<ch<.23*h and .30*h<y<.65*h:
                cards.append((x,y,cw,ch))
        targets=[];details=[]
        for x,y,cw,ch in sorted(cards):
            candidates=[]
            for left,right in [(.04,.8),(.07,.76),(.1,.78)]:
                patch=image[y+round(ch*.175):y+round(ch*.965),x+round(cw*left):x+round(cw*right)]
                candidates.append(self.classify(patch))
            key,score,margin=max(candidates,key=lambda row:row[1])
            if key and score>=.78 and margin>=.025:targets.append(key)
            details.append(dict(class_id=key,score=score,margin=margin))
        return tuple(dict.fromkeys(targets)),details

    def read(self,image):
        slots=[];details=[]
        for rect in (TRAY_RECTS if self.use_tray_vision else ()):
            patch=crop_rect(image,rect);key,score,margin=self.classify_tray(patch)
            reduced=cv2.resize(patch,(32,32)).astype(float)
            empty=descriptor(patch) is None or matches_empty_slot(reduced,self.empties)
            value='' if empty else key if score>=.78 and margin>=.025 else '?'
            slots.append(value);details.append(dict(class_id=key,score=score,margin=margin,empty=empty))
        stable=[]
        for i,value in enumerate(slots):
            self.streak[i]=self.streak[i]+1 if self.previous is not None and self.previous[i]==value else 1
            stable.append(value if self.streak[i]>=2 else '?')
        self.previous=slots
        targets=[];target_details=[]
        for rect in TARGET_RECTS:
            patch=crop_rect(image,rect);key,score,margin=self.classify(patch)
            # Blue check mark means already fulfilled; don't prioritize it.
            gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY);edge=np.concatenate([gray[:2].ravel(),gray[-2:].ravel(),gray[:,:2].ravel(),gray[:,-2:].ravel()])
            active=float(np.median(edge))>=180
            if key and score>=.78 and margin>=.025 and active:targets.append(key)
            target_details.append(dict(class_id=key,score=score,margin=margin))
        return tuple(stable),tuple(targets),dict(tray=details,targets=target_details)
