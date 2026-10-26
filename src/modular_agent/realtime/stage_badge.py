"""Small, infrequent stage-badge histogram check. No OCR or frame-count clock."""
import math
import cv2
import numpy as np


class StageBadge:
    def __init__(self,data,capture_roi,interval=.1):
        self.roi=data['roi'];self.capture_roi=capture_roi;self.refs=np.asarray(data['histograms'],float)
        if self.refs.ndim!=2 or self.refs.shape[1]!=18 or len(self.refs)<2 or not np.all(np.isfinite(self.refs)) or np.any(self.refs<0) or np.any(np.linalg.norm(self.refs,axis=1)==0):raise ValueError('invalid stage badge references')
        self.refs/=np.linalg.norm(self.refs,axis=1,keepdims=True)
        l,t,r,b=capture_roi;x1,y1,x2,y2=self.roi
        if not 0<=l<=x1<x2<=r<=1 or not 0<=t<=y1<y2<=b<=1:raise ValueError('stage badge outside capture ROI')
        self.interval=interval;self.last=None;self.stage=None;self.pending=None;self.since=None;self.confidence=0.
    def vector(self,image):
        l,t,r,b=self.capture_roi;x1,y1,x2,y2=self.roi;h,w=image.shape[:2]
        crop=image[max(0,round((y1-t)/(b-t)*h)):min(h,round((y2-t)/(b-t)*h)),max(0,round((x1-l)/(r-l)*w)):min(w,round((x2-l)/(r-l)*w))]
        if not crop.size:return None
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV);mask=(hsv[:,:,1]>80)&(hsv[:,:,2]>185)
        if np.count_nonzero(mask)<max(10,mask.size*.006):return None
        vector=np.bincount((hsv[:,:,0][mask]//10),minlength=18).astype(float)
        return vector/max(np.linalg.norm(vector),1e-8)
    def update(self,image,now):
        if not math.isfinite(now) or self.last is not None and now<self.last:raise ValueError('nonmonotonic stage clock')
        if self.last is not None and now-self.last<self.interval:return None
        self.last=now;vector=self.vector(image)
        if vector is None:self.pending=None;self.since=None;return None
        scores=self.refs@vector;order=np.argsort(scores);best=int(order[-1]);self.confidence=float(scores[best])
        if scores[best]<.75 or scores[best]-scores[order[-2]]<.12 or self.stage is not None and best<self.stage:
            self.pending=None;self.since=None;return None
        if best==self.stage:self.pending=None;self.since=None;return None
        if self.pending!=best:self.pending=best;self.since=now;return None
        if now-self.since<.1:return None
        self.stage=best;self.pending=None;self.since=None;return best
