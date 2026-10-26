"""Local motion features only: avatar and rope. No UI/OCR/model dependencies."""
import time
from collections import deque
import cv2
import numpy as np


def crop(image, rect):
    h,w=image.shape[:2];l,t,r,b=rect
    return image[round(t*h):round(b*h),round(l*w):round(r*w)]


class JumpRopeVision:
    def __init__(self,config,reference):
        self.config=config
        self.template=crop(reference,config['avatar_template']).copy()
        self.template_cache={}
        self.reference_arrow=self._arrow(reference,1.0,1.0,full=True)
        self.reset()

    def _arrow(self,image,client_w,client_h,full=False):
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,np.uint8([15,100,180]),np.uint8([40,255,255]))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if full: client_h,client_w=image.shape[:2]
        candidates=[]
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if not .009<w/client_w<.035 or not .008<h/client_h<.035:continue
            shape=cv2.approxPolyDP(contour,.08*cv2.arcLength(contour,True),True)
            if len(shape)!=3:continue
            pts=shape[:,0,:];bottom=pts[np.argmax(pts[:,1])]
            others=np.delete(pts,np.argmax(pts[:,1]),axis=0)
            if bottom[1]-max(others[:,1])<h*.4:continue
            if not x+w*.2<bottom[0]<x+w*.8:continue
            cx=(x+w/2)/client_w;cy=(y+h/2)/client_h
            if not full:cx+=self.config['roi'][0];cy+=self.config['roi'][1]
            left,right=(.35,.75) if full else (self.config['roi'][0]+.065,self.config['roi'][2]-.065)
            if left<cx<right and .15<cy<.6:candidates.append((cx,cy))
        return candidates[0] if len(candidates)==1 else None

    def reset(self):
        self.previous=[None for _ in self.config['rope_probes']]
        self.last_timestamp=None
        self.tracked_x=.565
        self.gray_history=deque(maxlen=3)
        self.motion_mask=None
        self.static_since=None
        self.reject_static=False

    def local_rect(self,rect):
        l,t,r,b=self.config['roi'];x1,y1,x2,y2=rect
        return [(x1-l)/(r-l),(y1-t)/(b-t),(x2-l)/(r-l),(y2-t)/(b-t)]

    def _candidates(self,mask,hsv,probe,client_w,client_h,family,local=False):
        c=self.config;x1,x2=probe;y1,y2=c['rope_y']
        rect=self.local_rect([x1,y1,x2,y2])
        band=mask if local else crop(mask,rect)
        colors=hsv if local else crop(hsv,rect)
        candidates=[]
        if not band.size:return candidates
        joined=cv2.morphologyEx(band,cv2.MORPH_CLOSE,np.ones((1,max(3,round(band.shape[1]*.18))),np.uint8))
        n,labels,stats,_=cv2.connectedComponentsWithStats(joined)
        for label in range(1,n):
            x,y,w,h,area=stats[label]
            if w<band.shape[1]*.65 or h/client_h>.035 or area<band.shape[1]*.5:continue
            yy,xx=np.where((labels==label)&(band!=0))
            if not len(xx):continue
            if len(np.unique(xx))<band.shape[1]*.5:continue
            slope,offset=np.polyfit(xx,yy,1)
            if float(np.percentile(np.abs(yy-(slope*xx+offset)),90))/client_h>.006:continue
            position=y1+float(np.mean(yy))/client_h
            points=[]
            for fraction in (.15,.5,.85):
                column=round(fraction*(band.shape[1]-1))
                chosen=np.abs(xx-column)<=1
                if chosen.any():points.append([x1+column/client_w,y1+float(np.median(yy[chosen]))/client_h])
            moving=None
            if self.motion_mask is not None:
                motion=crop(self.motion_mask,rect)
                moving=float(np.mean(motion[yy,xx]>0))
            candidates.append(dict(motion=moving,y=position,hue=float(np.median(colors[yy,xx,0])),saturation=float(np.median(colors[yy,xx,1])),points=points,family=family))
        return candidates

    def _select(self,candidates,previous,now):
        c=self.config
        if previous is None:return candidates[0] if len(candidates)==1 else None
        age=now-previous['time']
        if not 0<age<=c['association_max_age']:
            return candidates[0] if len(candidates)==1 else None
        predicted=previous['y']+previous['velocity']*age
        gate=c['association_gate']+abs(previous['velocity'])*age*.4
        choices=sorted((abs(candidate['y']-predicted),index) for index,candidate in enumerate(candidates))
        if not choices or choices[0][0]>gate:return None
        if len(choices)>1 and choices[1][0]-choices[0][0]<c['association_ambiguity']:return None
        return candidates[choices[0][1]]

    def _joint(self,left,right,now):
        c=self.config;choices=[]
        for a in left[:8]:
            for b in right[:8]:
                if abs(a['y']-b['y'])>=.10:continue
                hue_gap=abs(a['hue']-b['hue']);hue_gap=min(hue_gap,180-hue_gap)
                if min(a['saturation'],b['saturation'])>80 and hue_gap>25:continue
                points=a['points']+b['points']
                if len(points)<4:continue
                xy=np.array(points);coef=np.polyfit(xy[:,0]-self.tracked_x,xy[:,1],2)
                error=float(np.max(np.abs(np.polyval(coef,xy[:,0]-self.tracked_x)-xy[:,1])))
                if error>c['curve_max_error']:continue
                if abs(coef[1])>c.get('rope_max_center_slope',.70):continue
                if abs(coef[0])>c.get('rope_max_curvature',5.0):continue
                if np.max(np.abs(2*coef[0]*(xy[:,0]-self.tracked_x)+coef[1]))>c.get('rope_max_tangent_slope',1.3):continue
                if not c['rope_y'][0]-.03<=coef[2]<=c['rope_y'][1]+.03:continue
                # Repeated identical frames do not provide motion evidence.
                if self.reject_static and (self.motion_mask is None or max(a.get('motion') or 0,b.get('motion') or 0)<.025):continue
                static_penalty=.02 if self.motion_mask is not None and max(a.get('motion') or 0,b.get('motion') or 0)<.025 else 0
                score=error+static_penalty;valid=True
                for candidate,previous in zip((a,b),self.previous):
                    if previous is not None and 0<now-previous['time']<=c['association_max_age']:
                        age=now-previous['time'];distance=abs(candidate['y']-previous['y']-previous['velocity']*age)
                        if distance>c['association_gate']+abs(previous['velocity'])*age*.4:valid=False;break
                        score+=distance
                if valid:choices.append((score,a,b,coef,error))
        choices.sort(key=lambda item:item[0])
        if not choices:return None
        if len(choices)>1 and choices[1][0]-choices[0][0]<c['association_ambiguity']:return None
        return choices[0]

    def _check_pair_motion(self,pair,now):
        if pair is None:return None
        if self.motion_mask is None:return None if self.reject_static else pair
        moving=max(pair[1].get('motion') or 0,pair[2].get('motion') or 0)
        if moving>=.025:
            self.static_since=None;self.reject_static=False
            return pair
        if self.static_since is None:self.static_since=now
        if now-self.static_since>=.25:
            self.reject_static=True
            self.previous=[None,None]
            return None
        return pair

    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        if self.last_timestamp is not None and (now<=self.last_timestamp or now-self.last_timestamp>self.config['association_max_age']):self.reset()
        self.last_timestamp=now
        c=self.config;l,t,r,b=c['roi'];height,width=image.shape[:2]
        scene_changed=False;self.motion_mask=None
        if c.get('joint_shape_motion',False):
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            scene_changed=False
            self.motion_mask=None
            if self.gray_history and self.gray_history[0].shape==gray.shape:
                difference=cv2.absdiff(gray,self.gray_history[0])
                if np.mean(difference>30)>.55:
                    self.previous=[None,None];self.gray_history.clear();self.static_since=None;self.reject_static=False;scene_changed=True
                elif np.mean(difference>8)>.001:
                    self.motion_mask=np.uint8(difference>8)*255
            self.gray_history.append(gray)
        client_w,client_h=width/(r-l),height/(b-t)
        avatar=None;avatar_score=0.0;avatar_source=None
        arrow=self._arrow(image,client_w,client_h)
        if arrow is not None and self.reference_arrow is not None:
            avatar=arrow[1]+c['avatar_template'][1]-self.reference_arrow[1]
            avatar_source='arrow'
        else:
            search=crop(image,self.local_rect(c['avatar_search']))
            size=(max(2,round(client_w*(c['avatar_template'][2]-c['avatar_template'][0]))),max(2,round(client_h*(c['avatar_template'][3]-c['avatar_template'][1]))))
            if size not in self.template_cache:
                if len(self.template_cache)>4:self.template_cache.clear()
                self.template_cache[size]=cv2.resize(self.template,size)
            template=self.template_cache[size]
            if search.shape[0]>=size[1] and search.shape[1]>=size[0]:
                _,avatar_score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
                if np.isfinite(avatar_score) and avatar_score>=c['avatar_threshold']:
                    avatar=c['avatar_search'][1]+pos[1]/client_h
            avatar_source='template' if avatar is not None else None
        if arrow is not None:
            if abs(arrow[0]-self.tracked_x)>.01:self.previous=[None,None]
            self.tracked_x=arrow[0]
        probes=[[self.tracked_x-.065,self.tracked_x-.04],[self.tracked_x+.04,self.tracked_x+.065]]
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        mask=np.zeros(image.shape[:2],np.uint8)
        for low,high in c['rope_hsv_ranges']:mask|=cv2.inRange(hsv,np.uint8(low),np.uint8(high))
        predicted=[None if previous is None else previous['y']+previous['velocity']*max(0,now-previous['time']) for previous in self.previous]
        selected=[];counts=[];candidate_lists=[]
        for index,probe in enumerate(probes):
            previous=self.previous[index]
            if previous is not None and now-previous['time']>c['association_max_age']:previous=None;self.previous[index]=None
            candidates=self._candidates(mask,hsv,probe,client_w,client_h,'configured')
            chosen=self._select(candidates,previous,now)
            if chosen is None:
                colors=crop(hsv,self.local_rect([probe[0],c['rope_y'][0],probe[1],c['rope_y'][1]]))
                masks=[cv2.inRange(colors,np.uint8([max(0,hue-5),55,100]),np.uint8([min(179,hue+34),255,255])) for hue in range(0,180,30)]
                masks.append(cv2.inRange(colors,np.uint8([0,0,185]),np.uint8([179,55,255])))
                extra=[]
                for alternative in masks:
                    for trace in self._candidates(alternative,colors,probe,client_w,client_h,'changed',local=True):
                        if not any(abs(trace['y']-old['y'])<.003 and abs(trace['hue']-old['hue'])<10 for old in extra):extra.append(trace)
                chosen=self._select(extra,previous,now)
                candidates+=extra
            counts.append(len(candidates));selected.append(chosen);candidate_lists.append(candidates)
        if c.get('joint_shape_motion',False):
            # Joint selection prevents independent sides snapping to incompatible scenery.
            # Keep the fast configured candidate set when it already forms a valid pair.
            pair=self._joint([selected[0]],[selected[1]],now) if all(trace is not None for trace in selected) else None
            pair=self._check_pair_motion(pair,now)
            if pair is None:pair=self._check_pair_motion(self._joint(candidate_lists[0],candidate_lists[1],now),now)
            if pair is None:
                for index,probe in enumerate(probes):
                    colors=crop(hsv,self.local_rect([probe[0],c['rope_y'][0],probe[1],c['rope_y'][1]]))
                    for hue in range(0,180,30):
                        extra_mask=cv2.inRange(colors,np.uint8([max(0,hue-5),45,90]),np.uint8([min(179,hue+34),255,255]))
                        extra=self._candidates(extra_mask,colors,probe,client_w,client_h,'changed',local=True)
                        for trace in extra:
                            if not any(abs(trace['y']-old['y'])<.003 and abs(trace['hue']-old['hue'])<10 for old in candidate_lists[index]):candidate_lists[index].append(trace)
                    pale=cv2.inRange(colors,np.uint8([0,0,150]),np.uint8([179,65,255]))
                    if self.motion_mask is not None:
                        moving=crop(self.motion_mask,self.local_rect([probe[0],c['rope_y'][0],probe[1],c['rope_y'][1]]))
                        pale &= cv2.dilate(moving,np.ones((3,3),np.uint8))
                    for trace in self._candidates(pale,colors,probe,client_w,client_h,'changed',local=True):
                        if not any(abs(trace['y']-old['y'])<.003 and abs(trace['hue']-old['hue'])<10 for old in candidate_lists[index]):candidate_lists[index].append(trace)
                pair=self._check_pair_motion(self._joint(candidate_lists[0],candidate_lists[1],now),now)
            if pair is None:
                selected=[self._select(items,previous,now) for items,previous in zip(candidate_lists,self.previous)]
            counts=[len(items) for items in candidate_lists]
            valid_rope=pair is not None
            rope_y=curve_error=rope_slope=rope_curvature=None
            if pair is not None:
                _,a,b,coefficients,curve_error=pair;selected=[a,b]
                rope_y=float(coefficients[2]);rope_slope=float(coefficients[1]);rope_curvature=float(coefficients[0])
            points=[point for trace in selected if trace is not None for point in trace['points']] if valid_rope else []
        else:
            valid_rope=all(trace is not None for trace in selected)
            if valid_rope and abs(selected[0]['y']-selected[1]['y'])>=.10:valid_rope=False
            points=[point for trace in selected if trace is not None for point in trace['points']]
            rope_y=curve_error=rope_slope=rope_curvature=None
            if valid_rope and len(points)>=3:
                xy=np.array(points);coefficients=np.polyfit(xy[:,0]-self.tracked_x,xy[:,1],2)
                curve_error=float(np.max(np.abs(np.polyval(coefficients,xy[:,0]-self.tracked_x)-xy[:,1])))
                rope_y=float(coefficients[2]);rope_slope=float(coefficients[1]);rope_curvature=float(coefficients[0])
                if curve_error>c['curve_max_error'] or not c['rope_y'][0]-.03<=rope_y<=c['rope_y'][1]+.03:valid_rope=False
            elif valid_rope:valid_rope=False
        selection_method='fallback' if any(trace is not None and trace['family']=='changed' for trace in selected) else 'configured'
        saturation=float(np.mean([trace['saturation'] for trace in selected])) if valid_rope else None
        if not self.reject_static and (valid_rope or sum(trace is not None for trace in selected)==1):
            for index,trace in enumerate(selected):
                if trace is None:continue
                previous=self.previous[index];velocity=0.0
                if previous is not None and 0<now-previous['time']<=c['association_max_age']:
                    speed=(trace['y']-previous['y'])/(now-previous['time'])
                    velocity=float(np.clip(.6*speed+.4*previous['velocity'],-3,3))
                self.previous[index]=dict(y=trace['y'],time=now,velocity=velocity)
        return dict(valid=avatar is not None and valid_rope,avatar_valid=avatar is not None,
                    avatar_y=avatar,avatar_source=avatar_source,arrow_position=arrow,avatar_confidence=float(avatar_score),rope_valid=bool(valid_rope),
                    rope_y=rope_y if valid_rope else None,
                    hue=float(np.mean([trace['hue'] for trace in selected])) if valid_rope else None,
                    rope_points=points,curve_error=curve_error,rope_slope=rope_slope,rope_curvature=rope_curvature,
                    scene_changed=scene_changed,rope_rejection=None if valid_rope else 'stationary_candidate_unlock' if self.reject_static else 'joint_shape_motion_or_ambiguity',
                    probe_y=[trace['y'] for trace in selected if trace is not None],probe_candidates=counts,
                    probe_prediction=predicted,
                    color_changed=False,color_uncertain=False,
                    rope_saturation=saturation,selection_method=selection_method if valid_rope else None,
                    mode_hint=None,terminal=None,hud_valid=None,hearts=None)
