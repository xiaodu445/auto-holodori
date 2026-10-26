"""Tiny local white-digit shape matcher; no OCR engine or full-screen scan."""
import cv2
import numpy as np

def digit_shapes(image,roi=None):
    h,w=image.shape[:2]
    l,t,r,b=roi or (0,0,1,1);h=h/(b-t);w=w/(r-l)
    crop=image[max(0,round((.065-t)*h)):max(0,round((.215-t)*h)),max(0,round((.025-l)*w)):max(0,round((.145-l)*w))]
    if crop.size==0:return []
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV);mask=np.uint8((hsv[:,:,1]<60)&(hsv[:,:,2]>210))*255
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
    boxes=[s for s in stats[1:] if s[3]>.055*h and s[4]>.00065*h*w]
    boxes.sort(key=lambda s:s[0]);result=[]
    for x,y,width,height,area in boxes:
        glyph=mask[y:y+height,x:x+width];target=np.zeros((48,40),np.uint8);new_width=min(38,max(1,round(width*46/height)));small=cv2.resize(glyph,(new_width,46),interpolation=cv2.INTER_NEAREST)
        left=(40-new_width)//2;target[1:47,left:left+new_width]=small
        result.append(target>0)
    return result

class CountStageHint:
    def __init__(self,asset,roi=None):
        self.roi=roi;self.refs={k:np.array(v,dtype=bool) for k,v in asset['digits'].items()};self.pending=None;self.since=None;self.stage=None;self.last_count=None;self.last_evidence=None
    def update(self,image,now):
        glyphs=digit_shapes(image,self.roi)
        if not 1<=len(glyphs)<=2:
            self.pending=None;self.since=None;return None
        digits=[];scores=[]
        for glyph in glyphs:
            ranked=sorted(((k,float(np.count_nonzero(glyph&r)/max(1,np.count_nonzero(glyph|r)))) for k,r in self.refs.items()),key=lambda x:x[1],reverse=True)
            k,s=ranked[0];gap=s-ranked[1][1];digits.append(k if s>=.65 and gap>=.08 else None);scores.append(dict(best=k,score=s,margin=gap))
        # Unknown unit digit can still yield a conservative tens interval.
        if digits[0] is None:
            self.pending=None;self.since=None;return None
        low=int(digits[0])*10 if len(digits)==2 else int(digits[0]);high=low+9 if len(digits)==2 else low
        count=int(''.join(digits)) if all(d is not None for d in digits) else None
        stage=next(i for i,b in reversed(list(enumerate([0,10,30,50,70]))) if low>=b)
        self.last_count=count;self.last_evidence=dict(time=now,count=count,count_interval=[low,high],scores=scores,stage_hint=stage+1)
        if self.stage is not None and stage<=self.stage:return None
        if stage!=self.pending:self.pending=stage;self.since=now;return None
        if now-self.since<.05:return None
        self.stage=stage;return stage


class CountThirtyShift:
    """User-directed stage-three switch after stable local count >=30."""
    def __init__(self,asset,roi=None):
        self.counter=CountStageHint(asset,roi);self.done=False;self.event=None
    def update(self,image,now,bank):
        stage=self.counter.update(image,now)
        if not self.done and stage is not None and stage>=2:
            changed=bank.force_count_stage(2,now)
            self.done=True;self.event=dict(time=now,threshold=30,changed=changed,count_reading=self.counter.last_evidence)
        return self.event
