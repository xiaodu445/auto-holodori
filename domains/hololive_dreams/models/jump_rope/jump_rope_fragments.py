"""Visible moving edge fragments; center gap is never required to be visible."""
import cv2
import numpy as np
from collections import deque

class FragmentTracker:
    def __init__(self):
        self.full=None
        self.positions=deque()
        self.locked_y=None;self.locked_shape=None
    def reset(self):
        self.full=None;self.positions.clear();self.locked_y=None;self.locked_shape=None
    def accept(self,o,now):
        if not o.get('rope_valid'):return o
        y=o['rope_y'];slope=o.get('rope_slope') or 0;curvature=o.get('rope_curvature') or 0
        if self.locked_y is not None:
            if abs(y-self.locked_y)<.012 and (self.locked_shape is None or abs(slope-self.locked_shape[0])<.10 and abs(curvature-self.locked_shape[1])<.8):
                return self.reject(o,'stationary_geometry')
            self.locked_y=None;self.locked_shape=None;self.positions.clear()
        self.positions.append((now,y,slope,curvature))
        while self.positions and now-self.positions[0][0]>.35:self.positions.popleft()
        if len(self.positions)>=5 and now-self.positions[0][0]>=.28 and np.ptp([a[1] for a in self.positions])<.004 and np.ptp([a[2] for a in self.positions])<.06 and np.ptp([a[3] for a in self.positions])<.5:
            self.locked_y=y;self.locked_shape=(slope,curvature);self.full=None
            return self.reject(o,'stationary_geometry')
        if o.get('visible_sides',2)==2:
            pts=np.array(o['rope_points']);center=o.get('tracked_center_x',.565)
            coef=np.polyfit(pts[:,0]-center,pts[:,1],2);speed=0.0
            if self.full and 0<now-self.full['time']<=.12:
                speed=float(np.clip((y-self.full['coef'][2])/(now-self.full['time']),-4.5,4.5))
            self.full=dict(time=now,coef=coef,center=center,speed=speed)
        return o
    @staticmethod
    def reject(o,reason):
        o.update(valid=False,rope_valid=False,rope_y=None,rope_points=[],rope_rejection=reason)
        return o
    def detect(self,gray,motion,c,center,now):
        h,w=gray.shape;l,t,r,b=c['roi'];cw=w/(r-l);ch=h/(b-t)
        edges=cv2.Canny(gray,25,70)&motion
        # Wider lateral strips avoid the avatar and expose more of a broken rope.
        bands=[(center-.088,center-.035),(center+.035,center+.088)]
        strips=[]
        for xa,xb in bands:
            x1=max(0,round((xa-l)*cw));x2=min(w,round((xb-l)*cw))
            strip=edges[:,x1:x2]
            if not strip.size:strips.append([]);continue
            lines=cv2.HoughLinesP(strip,1,np.pi/180,threshold=6,minLineLength=max(6,round(cw*.008)),maxLineGap=2)
            items=[]
            for x,y,xx,yy in [] if lines is None else np.asarray(lines).reshape(-1,4):
                if abs(xx-x)<cw*.008:continue
                pts=np.array([[l+(x+x1)/cw,t+y/ch],[l+(xx+x1)/cw,t+yy/ch]])
                slope=(pts[1,1]-pts[0,1])/(pts[1,0]-pts[0,0])
                if abs(slope)>1.5:continue
                if not c['rope_y'][0]<=np.mean(pts[:,1])<=c['rope_y'][1]:continue
                if any(np.linalg.norm(np.mean(pts,axis=0)-np.mean(a,axis=0))<.004 for a in items):continue
                items.append(pts)
                if len(items)>=16:break
            strips.append(items)
        choices=[]
        for a in strips[0]:
            for bb in strips[1]:
                pts=np.concatenate([a,bb]);coef=np.polyfit(pts[:,0]-center,pts[:,1],2)
                error=float(np.max(np.abs(np.polyval(coef,pts[:,0]-center)-pts[:,1])))
                if error>.005 or abs(coef[1])>.9 or abs(coef[0])>9:continue
                if not c['rope_y'][0]<=coef[2]<=c['rope_y'][1]:continue
                choices.append((coef,pts,error,2))
        if not choices and self.full and 0<now-self.full['time']<=.12 and abs(center-self.full['center'])<.01:
            for side in strips:
                for pts in side:
                    old=self.full['coef'];delta=pts[:,1]-np.polyval(old,pts[:,0]-center)
                    predicted_shift=self.full.get('speed',0)*(now-self.full['time'])
                    if np.ptp(delta)>.004 or abs(np.mean(delta)-predicted_shift)>.035+abs(predicted_shift)*.6:continue
                    coef=old.copy();coef[2]+=np.mean(delta)
                    choices.append((coef,pts,float(np.ptp(delta)),1))
        if not choices:return None
        previous=self.full
        prediction=None
        if previous and now-previous['time']<=.12:prediction=previous['coef'][2]+previous.get('speed',0)*(now-previous['time'])
        def score(a):
            if prediction is None:return a[2]
            return a[2]+abs(a[0][2]-prediction)+.01*abs(a[0][1]-previous['coef'][1])+.001*abs(a[0][0]-previous['coef'][0])
        choices.sort(key=score)
        first=choices[0]
        # Duplicate top/bottom edges of the same rope are one candidate.
        other=next((a for a in choices[1:] if abs(a[0][2]-first[0][2])>.008),None)
        if other is not None and score(other)-score(first)<.008:return None
        coef,pts,error,sides=first
        if prediction is not None and abs(coef[2]-prediction)>max(.06,.035+abs(previous.get('speed',0))*(now-previous['time'])*.6):return None
        return dict(rope_valid=True,rope_y=float(coef[2]),rope_points=pts.tolist(),rope_slope=float(coef[1]),rope_curvature=float(coef[0]),curve_error=error,visible_sides=sides,selection_method='moving_fragments' if sides==2 else 'one_side_shape_projection',rope_rejection=None,shape_projected=sides==1,rope_coefficients=coef.tolist())
