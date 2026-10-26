"""Small lower-window ROI, frame difference + current edges; no color dependency."""
import time
from collections import deque
import cv2
import numpy as np


class LocalMotionVision:
    def __init__(self,config,reference):
        self.c=config
        x1,y1,x2,y2=config['avatar_template'];h,w=reference.shape[:2]
        self.template=reference[round(y1*h):round(y2*h),round(x1*w):round(x2*w)].copy()
        self.reset()
    def reset(self):
        self.history=deque(maxlen=3);self.last_time=None;self.last_line=None
    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        c=self.c;l,t,r,b=c['roi'];h,w=image.shape[:2];cw=w/(r-l);ch=h/(b-t)
        if self.last_time is not None and (now<=self.last_time or now-self.last_time>.08):self.reset()
        self.last_time=now
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        edges=cv2.Canny(gray,40,100)
        avatar_y=None;score=0.0
        ax,ay,bx,by=c['avatar_search']
        search=gray[max(0,round((ay-t)*ch)):min(h,round((by-t)*ch)),max(0,round((ax-l)*cw)):min(w,round((bx-l)*cw))]
        x1,y1,x2,y2=c['avatar_template'];size=(max(3,round((x2-x1)*cw)),max(3,round((y2-y1)*ch)))
        template=cv2.cvtColor(cv2.resize(self.template,size),cv2.COLOR_BGR2GRAY)
        if np.count_nonzero(template)>5 and search.shape[0]>=size[1] and search.shape[1]>=size[0]:
            _,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
            if np.isfinite(score) and score>=c['avatar_threshold']:avatar_y=ay+pos[1]/ch
        scene=False;motion=np.zeros_like(gray)
        if self.history:
            old_time,old=self.history[0]
            if old.shape==gray.shape and now-old_time<=.12:
                delta=cv2.absdiff(gray,old)
                scene=float(np.mean(delta>20))>.30
                if not scene:motion=np.uint8(delta>12)*255
        if scene:self.history.clear();self.last_line=None
        self.history.append((now,gray))
        # Keep only present-frame edges near changing pixels, not old-position traces.
        moving_edges=edges & cv2.dilate(motion,np.ones((3,3),np.uint8))
        # Feet/body animation must not masquerade as a rope.
        moving_edges[:,max(0,round((.54-l)*cw)):min(w,round((.59-l)*cw))]=0
        raw=cv2.HoughLinesP(moving_edges,1,np.pi/180,threshold=max(8,round(cw*.009)),minLineLength=max(10,round(cw*.02)),maxLineGap=max(2,round(cw*.004)))
        candidates=[]
        for line in [] if raw is None else np.asarray(raw).reshape(-1,4):
            x1,y1,x2,y2=map(int,line)
            if x2<x1:x1,y1,x2,y2=x2,y2,x1,y1
            dx=x2-x1
            if dx<cw*.02:continue
            slope=(y2-y1)/ch/(dx/cw)
            if abs(slope)>.8:continue
            nx1=l+x1/cw;nx2=l+x2/cw;ny1=t+y1/ch
            center_y=ny1+slope*(.565-nx1)
            if not c['local_jump_band'][0]<=center_y<=c['local_jump_band'][1]:continue
            if any(abs(center_y-a['y'])<.008 for a in candidates):continue
            candidates.append(dict(y=float(center_y),slope=float(slope),points=[[float(nx1),float(ny1)],[float((nx1+nx2)/2),float(t+(y1+y2)/2/ch)],[float(nx2),float(t+y2/ch)]],length=float(dx/cw)))
        chosen=None;speed=None
        if not scene and candidates:
            if self.last_line and 0<now-self.last_line['time']<=.12:
                age=now-self.last_line['time'];prediction=self.last_line['y']+self.last_line['speed']*age
                ranked=sorted(candidates,key=lambda a:abs(a['y']-prediction))
                if abs(ranked[0]['y']-prediction)<=.07 and (len(ranked)==1 or abs(ranked[1]['y']-prediction)-abs(ranked[0]['y']-prediction)>.006):chosen=ranked[0]
            elif len(candidates)==1:chosen=candidates[0]
            # With no history, do not guess between several moving strips.
        if chosen:
            speed=0.0
            if self.last_line and 0<now-self.last_line['time']<=.12:speed=(chosen['y']-self.last_line['y'])/(now-self.last_line['time'])
            self.last_line=dict(time=now,y=chosen['y'],speed=float(np.clip(speed,-3,3)))
        elif self.last_line and now-self.last_line['time']>.12:self.last_line=None
        boxes=[]
        n,_,stats,_=cv2.connectedComponentsWithStats(motion)
        for x,y,bw,bh,area in stats[1:]:
            if area>=8:boxes.append([l+float(x)/cw,t+float(y)/ch,l+float(x+bw)/cw,t+float(y+bh)/ch])
            if len(boxes)>=12:break
        return dict(valid=avatar_y is not None and chosen is not None,avatar_valid=avatar_y is not None,avatar_y=avatar_y,avatar_confidence=float(score),avatar_source='local_body_gray' if avatar_y is not None else None,
            rope_valid=chosen is not None,rope_y=chosen['y'] if chosen else None,rope_points=chosen['points'] if chosen else [],rope_slope=chosen['slope'] if chosen else None,rope_curvature=0 if chosen else None,
            motion_speed=speed,motion_boxes=boxes,motion_fraction=float(np.mean(motion>0)),scene_changed=scene,curve_error=0 if chosen else None,probe_candidates=[len(candidates)],
            rope_rejection='scene_change' if scene else 'no_unique_moving_line' if chosen is None else None,terminal=None,mode_hint=None)


class LocalMotionController:
    def __init__(self,config):
        self.c=config;self.jumps=0;self.crossings=0;self.mode='local_motion';self.reset_motion()
    def reset_motion(self):
        self.state='acquiring';self.ground_count=0;self.line_count=0;self.consumed=False;self.last_line=None;self.release_at=None;self.jump_sent_at=None;self.seen_airborne=False;self.last_time=None
    def debug_snapshot(self):
        return dict(ground_frames=self.ground_count,pass_consumed=self.consumed,jump_outstanding=self.jump_sent_at is not None,motion_samples=self.line_count,tracking_established=self.last_line is not None)
    def step(self,o,now,down=False,frame_age=0):
        d=dict(down=False,state=self.state,mode=self.mode,input_inhibited=None,prediction=None,pending=None,motion_speed=o.get('motion_speed'))
        if o.get('terminal') in ('success','failure'):d['stop']=o['terminal'];return d
        if o.get('scene_changed') or frame_age>self.c['max_frame_age'] or self.last_time is not None and not 0<now-self.last_time<=.08:
            self.reset_motion();self.last_time=now;d['input_inhibited']='scene_or_stale_reacquire';return d
        self.last_time=now
        baseline=self.c['avatar_template'][1]
        ground=o.get('avatar_valid') and o.get('avatar_y') is not None and abs(o['avatar_y']-baseline)<=self.c['ground_tolerance']
        self.ground_count=self.ground_count+1 if ground else 0
        if not o.get('avatar_valid'):self.state='avatar_unknown'
        elif not ground:
            self.state='airborne'
            if self.jump_sent_at is not None:self.seen_airborne=True
        elif self.ground_count>=3:
            self.state='grounded'
            if self.jump_sent_at is not None and (self.seen_airborne or now-self.jump_sent_at>.30):
                self.jump_sent_at=None;self.seen_airborne=False
        if down and self.release_at is not None and now<self.release_at and o.get('avatar_valid'):d['down']=True
        if o.get('rope_valid'):
            self.last_line=now;self.line_count+=1
        else:
            self.line_count=0
            if self.last_line is not None and now-self.last_line>.20:self.consumed=False
        if not self.c.get('experimental_input'):d['input_inhibited']='judgment_only'
        elif not ground or self.ground_count<3:d['input_inhibited']='landing_not_confirmed'
        elif self.consumed:d['input_inhibited']='same_pass_consumed'
        elif not o.get('rope_valid') or self.line_count<2:d['input_inhibited']='waiting_for_moving_line'
        elif self.jump_sent_at is not None:d['input_inhibited']='jump_outstanding'
        else:
            self.jumps+=1;self.crossings+=1;self.consumed=True;self.jump_sent_at=now;self.seen_airborne=False;self.release_at=now+self.c['pulse_seconds'];self.state='jump_requested'
            d.update(down=True,trigger='local_frame_difference_line')
        d.update(state=self.state,jumps=self.jumps,crossings=self.crossings,missing_features=[key for key in ('avatar','rope') if not o.get(key+'_valid')])
        return d
