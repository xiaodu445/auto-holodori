"""Whole-rope diagnostic tracker: hand anchors, parametric curve and bounded occlusion.
No control calibration or jump input. Reference points are manually annotated priors.
"""
from collections import deque
import time
import cv2
import numpy as np

# Client-normalized reference annotations; not automatically detected truth.
REFERENCE_CURVE=np.array([[.231,.557],[.29,.40],[.36,.23],[.43,.135],[.51,.085],
                          [.59,.066],[.66,.080],[.72,.126],[.77,.215],[.80,.30],[.819,.397]])
HAND_RECTS=[[.214,.529,.248,.585],[.800,.366,.836,.424]]
HAND_SEARCH=[[.18,.45,.28,.61],[.77,.32,.86,.48]]
HAND_POINTS=[[.231,.557],[.819,.397]]

def rect(image,r):
    h,w=image.shape[:2];x,y,xx,yy=r
    return image[round(y*h):round(yy*h),round(x*w):round(xx*w)]

class WholeRopeVision:
    def __init__(self,config,reference):
        self.c=config
        if type(config.get('whole_shape_model',False)) is not bool:raise ValueError('invalid whole_shape_model')
        limits=config.get('whole_continuity',{})
        for key,default in [('max_speed',6.0),('max_acceleration',90.0),('position_noise',.008)]:
            value=limits.get(key,default)
            if type(value) not in (int,float) or not np.isfinite(value) or value<0 or key!='position_noise' and value==0:raise ValueError('invalid whole_continuity '+key)
        self.banks=[[(cv2.cvtColor(rect(reference,r),cv2.COLOR_BGR2GRAY),r,point)] for r,point in zip(HAND_RECTS,HAND_POINTS)]
        path=config.get('whole_hand_pose')
        pose=cv2.imread(path) if path else None
        if pose is not None:
            rects=[[.204,.581,.243,.643],[.788,.421,.827,.472]];points=[[.225,.616],[.802,.445]]
            for i,(r,point) in enumerate(zip(rects,points)):self.banks[i].append((cv2.cvtColor(rect(pose,r),cv2.COLOR_BGR2GRAY),r,point))
        self.reset()
    def reset(self):
        self.old=None;self.old_time=None;self.curve=None;self.velocity=None;self.background_low=None;self.background_high=None;self.variation=None
        self.track_id=getattr(self,"track_id",0);self.pending_curve=None;self.pending_time=None;self.pending_velocity=None;self.pending_count=0
        self.continuity_rejections=0;self.tracking_status="acquiring";self.last_residual=None
        self.seen=None;self.confirmed_time=None;self.full_confirmed_time=None;self.now=None;self.frame_count=0;self.anchor_history=[None,None];self.center_history=deque(maxlen=60)
    def _local(self,r):
        l,t,rr,b=self.c['roi'];x,y,xx,yy=r
        return [(x-l)/(rr-l),(y-t)/(b-t),(xx-l)/(rr-l),(yy-t)/(b-t)]
    def _anchors(self,gray,now,cw,ch):
        anchors=[];info=[]
        l,t,_,_=self.c['roi']
        for i,search_r in enumerate([[.18,.43,.29,.68],[.76,.30,.86,.51]]):
            search=rect(gray,self._local(search_r));confidence=0.0;found=None
            for raw_template,template_r,point in self.banks[i]:
                size=(max(3,round((template_r[2]-template_r[0])*cw)),max(3,round((template_r[3]-template_r[1])*ch)))
                template=cv2.resize(raw_template,size)
                if search.shape[0]<size[1] or search.shape[1]<size[0]:continue
                _,score,_,pos=cv2.minMaxLoc(cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED))
                if np.isfinite(score) and score>confidence:
                    confidence=float(score)
                    found=np.array([(search_r[0]-l)*cw+pos[0]+(point[0]-template_r[0])*cw,(search_r[1]-t)*ch+pos[1]+(point[1]-template_r[1])*ch]) if confidence>=.58 else None
            if found is not None and not ((.48<=t+found[1]/ch<=.64) if i==0 else (.33<=t+found[1]/ch<=.49)):found=None
            source='measured'
            previous=self.anchor_history[i]
            if found is not None and previous is not None and now-previous['time']<=.12 and np.linalg.norm((found-previous['point'])/[cw,ch])>min(.035,.006+1.2*(now-previous['time'])):found=None
            if found is not None:self.anchor_history[i]=dict(point=found,time=now)
            elif previous is not None and now-previous['time']<=.12:found=previous['point'];source='predicted'
            else:
                # New shaker identities can invalidate appearance templates. A slot prior
                # enables a search, but is explicitly NOT a measured hand landmark.
                source='slot_prior';slot=[.225,.59] if i==0 else [.805,.44]
                found=np.array([(slot[0]-l)*cw,(slot[1]-t)*ch])
            anchors.append(found)
            info.append(dict(point=None if found is None else [float(l+found[0]/cw),float(t+found[1]/ch)],source=source,confidence=float(confidence)))
        return anchors,info
    @staticmethod
    def _arch(u,upper=True):
        ref=REFERENCE_CURVE
        s=(ref[:,0]-ref[0,0])/(ref[-1,0]-ref[0,0])
        chord=ref[0,1]*(1-s)+ref[-1,1]*s
        profile=chord-ref[:,1];profile/=np.max(profile)
        return np.interp(u if upper else 1-u,s,profile)
    def _seed(self,anchors,amplitude,cw,ch):
        if self.c.get('whole_shape_model',False):
            u=np.linspace(0,1,41)
            return anchors[0][None,:]*(1-u[:,None])+anchors[1][None,:]*u[:,None]+np.column_stack([np.zeros(41),-self._arch(u,amplitude>=0)*amplitude*ch])
        # Parametric reference arc; both x and y are indexed by arc position.
        ref=REFERENCE_CURVE.copy();s=(ref[:,0]-ref[0,0])/(ref[-1,0]-ref[0,0])
        chord=ref[0,1]*(1-s)+ref[-1,1]*s;offset=ref[:,1]-chord
        offset/=max(abs(offset));u=np.linspace(0,1,41)
        warp=np.interp(u,s,offset)
        return anchors[0][None,:]*(1-u[:,None])+anchors[1][None,:]*u[:,None]+np.column_stack([np.zeros(41),warp*amplitude*ch])
    @staticmethod
    def _sample(field,points):
        h,w=field.shape;xs=np.clip(np.rint(points[:,0]).astype(int),0,w-1);ys=np.clip(np.rint(points[:,1]).astype(int),0,h-1)
        values=field[ys,xs].astype(float)
        values[(points[:,0]<0)|(points[:,0]>=w)|(points[:,1]<0)|(points[:,1]>=h)]=1000
        return values
    def _partial_allowed(self):
        return self.curve is not None and self.full_confirmed_time is not None and self.now is not None and self.now-self.full_confirmed_time<=.12
    def _full_support(self,observed,anchor_info):
        threshold=.40 if self.c.get('whole_shape_model',False) else (.65 if any(x['source']=='slot_prior' for x in anchor_info) else .45)
        return np.mean(observed[2:-2])>=threshold and np.mean(observed[2:20])>=.22 and np.mean(observed[21:-2])>=.22
    def _evidence(self,seed,edge_distance,moving_distance,gray,cw,ch,temporal):
        cached=getattr(self,'evidence_cache',{}).get(id(seed))
        if cached is not None:return cached
        tangent=np.gradient(seed,axis=0);length=np.linalg.norm(tangent,axis=1);normal=np.column_stack([-tangent[:,1],tangent[:,0]])/np.maximum(length[:,None],1)
        offsets=np.arange(-7,8,dtype=float)
        options=seed[:,None,:]+normal[:,None,:]*offsets[None,:,None]
        shape=options.shape;flat=options.reshape(-1,2)
        cost=self._sample(edge_distance,flat).reshape(shape[:2])
        motion=self._sample(moving_distance,flat).reshape(shape[:2])
        # No hue gate. Current edge evidence, motion and a small displacement penalty.
        total=cost+np.minimum(motion,12)*(.22 if temporal else .45)+abs(offsets)[None,:]*.10
        ridge=None
        if self.c.get('whole_shape_model',False):
            center=self._sample(gray,flat).reshape(shape[:2]);ridge=np.zeros_like(center)
            for radius in (2,4,6):
                plus=self._sample(gray,(options+normal[:,None,:]*radius).reshape(-1,2)).reshape(shape[:2])
                minus=self._sample(gray,(options-normal[:,None,:]*radius).reshape(-1,2)).reshape(shape[:2])
                a=center-plus;b=center-minus
                ridge=np.maximum(ridge,np.where(a*b>0,np.minimum(abs(a),abs(b)),0))
            # Thin bright OR dark ridges; no specific hue or brightness gate.
            total+=np.maximum(0,14-ridge)*.65
        return self._finish_evidence(options,total,cost,motion,ridge,cw,ch,temporal)
    def _finish_evidence(self,options,total,cost,motion,ridge,cw,ch,temporal):
        best=np.argmin(total,axis=1);points=options[np.arange(41),best]
        distance=cost[np.arange(41),best];moving=motion[np.arange(41),best]
        observed=(distance<=1.8)&((moving<=3.5) if not temporal else (moving<=5))
        if ridge is not None:
            observed=(distance<=4)&(moving<=5)&(ridge[np.arange(41),best]>=12)
            # Conservative body interiors: the rope is hidden here, so these
            # pixels cannot be used as rope measurements. Coordinates are priors.
            xx=self.c['roi'][0]+points[:,0]/cw;yy=self.c['roi'][1]+points[:,1]/ch
            if self.variation is not None:observed &= self._sample(self.variation,points)>=10
            for x,width,top,bottom in [(.37,.022,.43,.66),(.47,.020,.40,.63),(.565,.025,.37,.62),(.65,.022,.35,.59),(.73,.022,.33,.57)]:
                observed &= ~((abs(xx-x)<width)&(yy>top)&(yy<bottom))
        observed[[0,-1]]=False
        # Require evidence on both halves; a single obstacle edge is insufficient.
        coverage=float(np.mean(observed[2:-2]));left=float(np.mean(observed[2:20]));right=float(np.mean(observed[21:-2]))
        score=coverage-.012*float(np.mean(np.minimum(distance[2:-2],12)))
        if temporal and self._partial_allowed():
            indices=np.flatnonzero(observed[2:-2])+2
            # During occlusion, spread-out visible samples correct the previous
            # model. They need not cover both halves, but cannot be a tiny blob.
            if len(indices)>=10 and indices[-1]-indices[0]>=12:score+=.20
            else:score-=.3
        elif left<.22 or right<.22:score-=.3
        return score,points,observed
    def _prepare_evidence(self,seeds,edge_distance,moving_distance,gray,cw,ch):
        # Batch feature sampling for the arc family. Mathematical results match
        # scalar evaluation, with much less per-candidate array/setup overhead.
        self.evidence_cache={}
        if not seeds or not self.c.get('whole_shape_model',False):return
        curves=np.array([seed for seed,_ in seeds]);tangent=np.gradient(curves,axis=1)
        normals=np.stack([-tangent[:,:,1],tangent[:,:,0]],axis=2)/np.maximum(np.linalg.norm(tangent,axis=2)[:,:,None],1)
        offsets=np.arange(-7,8,dtype=float)
        options=curves[:,:,None,:]+normals[:,:,None,:]*offsets[None,None,:,None]
        shape=options.shape[:3];flat=options.reshape(-1,2)
        cost=self._sample(edge_distance,flat).reshape(shape);motion=self._sample(moving_distance,flat).reshape(shape)
        temporal=np.array([flag for _,flag in seeds]);factor=np.where(temporal,.22,.45)
        total=cost+np.minimum(motion,12)*factor[:,None,None]+abs(offsets)[None,None,:]*.10
        center=self._sample(gray,flat).reshape(shape);ridge=np.zeros_like(center)
        for radius in (2,4,6):
            plus=self._sample(gray,(options+normals[:,:,None,:]*radius).reshape(-1,2)).reshape(shape)
            minus=self._sample(gray,(options-normals[:,:,None,:]*radius).reshape(-1,2)).reshape(shape)
            a=center-plus;b=center-minus
            ridge=np.maximum(ridge,np.where(a*b>0,np.minimum(abs(a),abs(b)),0))
        total+=np.maximum(0,14-ridge)*.65
        for i,(seed,flag) in enumerate(seeds):
            self.evidence_cache[id(seed)]=self._finish_evidence(options[i],total[i],cost[i],motion[i],ridge[i],cw,ch,flag)
    def _continuous(self,points,now,cw,ch):
        """Gate ALL candidates before they can replace state, including reacquisition seeds."""
        prior=self.curve if self.curve is not None else self.pending_curve
        then=self.old_time if self.curve is not None else self.pending_time
        velocity=self.velocity if self.curve is not None else self.pending_velocity
        if prior is None or then is None:return True
        dt=now-then
        if not 0<dt<=.08:return False
        cfg=self.c.get('whole_continuity',{})
        max_speed=cfg.get('max_speed',6.0);max_acc=cfg.get('max_acceleration',90.0)
        noise=cfg.get('position_noise',.008);units=np.array([cw,ch])
        step=np.linalg.norm((points-prior)/units,axis=1)
        if np.quantile(step,.95)>max_speed*dt+noise:return False
        if velocity is not None:
            prediction=prior+velocity*dt
            residual=np.linalg.norm((points-prediction)/units,axis=1)
            self.last_residual=float(np.quantile(residual,.95))
            if self.last_residual>noise+.5*max_acc*dt*dt:return False
        old_length=np.sum(np.linalg.norm(np.diff(prior,axis=0)/units,axis=1))
        new_length=np.sum(np.linalg.norm(np.diff(points,axis=0)/units,axis=1))
        return abs(new_length-old_length)<=max(.015,old_length*.12)
    def _fit_candidate(self,chosen,temporal_seed,anchors,anchor_info,cw,ch):
        _,raw,raw_observed,temporal=chosen
        detected=raw.copy();observed=raw_observed.copy()
        measured=observed.copy();measured[[0,-1]]=[a['source']=='measured' for a in anchor_info]
        if anchor_info[0]['source']!='slot_prior':detected[0]=anchors[0]
        if anchor_info[1]['source']!='slot_prior':detected[-1]=anchors[1]
        if self.c.get('whole_shape_model',False):
            return self._fit_shape(detected,observed,temporal,anchors,anchor_info,cw,ch)
        u=np.linspace(0,1,41);basis=np.column_stack([np.sin(k*np.pi*u) for k in range(1,6)])
        if self.curve is None or not temporal:
            smooth=detected.copy()
            for axis in (0,1):
                chord=detected[0,axis]*(1-u)+detected[-1,axis]*u
                coeff=np.linalg.lstsq(np.vstack([basis[measured],np.eye(5)*.08]),np.r_[detected[measured,axis]-chord[measured],np.zeros(5)],rcond=None)[0]
                smooth[:,axis]=chord+basis@coeff
        else:
            coeff=np.linalg.lstsq(np.vstack([basis[measured],np.eye(5)*.15]),np.vstack([(detected-temporal_seed)[measured],np.zeros((5,2))]),rcond=None)[0]
            smooth=temporal_seed+basis@coeff
        observed &= np.linalg.norm(smooth-detected,axis=1)<=max(4,ch*.008)
        coverage=float(np.mean(observed[2:-2]))
        # A partial fragment must not indefinitely renew its own shape prior.
        if not self._full_support(observed,anchor_info) and not (temporal and self._partial_allowed() and coverage>=.25):return None
        return smooth,detected,observed,coverage
    def _fit_shape(self,detected,observed,temporal,anchors,anchor_info,cw,ch):
        # Four vertical parameters: arch, bounded asymmetry, two endpoint offsets.
        # The hidden half shares the same parameters as the visible fragments.
        u=np.linspace(0,1,41)
        chord=anchors[0][None,:]*(1-u[:,None])+anchors[1][None,:]*u[:,None]
        use=observed.copy();use[[0,-1]]=False
        if np.count_nonzero(use)<10:return None
        target=(detected-chord)[use,1]/ch
        arch=self._arch(u,np.median(target)<=0)
        basis=np.column_stack([-arch,-arch*(2*u-1),1-u,u])
        design=basis[use];weights=np.ones(len(target))
        regularizer=np.diag([.02,.12,1.5,1.5])
        for _ in range(4):
            coeff=np.linalg.lstsq(np.vstack([design*weights[:,None],regularizer]),np.r_[target*weights,np.zeros(4)],rcond=None)[0]
            coeff[0]=np.clip(coeff[0],-.30,.56)
            coeff[1]=np.clip(coeff[1],-(abs(coeff[0])*.40+.003),abs(coeff[0])*.40+.003)
            coeff[2:]=np.clip(coeff[2:],-.035,.035)
            error=abs(design@coeff-target);weights=np.minimum(1,.006/np.maximum(error,1e-6))
        smooth=chord.copy();smooth[:,1]+=basis@coeff*ch
        # Appearance anchors are uncertain priors, especially when shaker
        # identity/pose changes. Two bounded horizontal endpoint corrections
        # let visible rope segments refine them without free point deformation.
        xb=np.column_stack([1-u,u]);xdesign=xb[use];xtarget=(detected-chord)[use,0]/cw
        xcoeff=np.linalg.lstsq(np.vstack([xdesign*weights[:,None],np.eye(2)*1.5]),np.r_[xtarget*weights,np.zeros(2)],rcond=None)[0]
        smooth[:,0]+=xb@np.clip(xcoeff,-.02,.02)*cw
        observed &= np.linalg.norm(smooth-detected,axis=1)<=max(4,ch*.008)
        coverage=float(np.mean(observed[2:-2]))
        if not self._full_support(observed,anchor_info) and not (temporal and self._partial_allowed() and coverage>=.25):return None
        return smooth,detected,observed,coverage
    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        if self.old_time is not None and not 0<now-self.old_time<=.08:self.reset()
        # Bound inference work; normalized outputs remain relative to the client window.
        scale=min(1,640/image.shape[1]);small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if self.old is not None and self.old.shape!=gray.shape:self.reset()
        h,w=gray.shape;l,t,r,b=self.c['roi'];cw=w/(r-l);ch=h/(b-t)
        delta=np.zeros_like(gray) if self.old is None or self.old.shape!=gray.shape else cv2.absdiff(gray,self.old)
        scene=bool(np.mean(delta>30)>.45)
        if scene:self.reset()
        if self.c.get('whole_shape_model',False):
            current=gray.astype(np.float32)
            if self.background_low is None:self.background_low=current.copy();self.background_high=current.copy()
            else:
                self.background_low=np.minimum(current,self.background_low+2)
                self.background_high=np.maximum(current,self.background_high-2)
            self.variation=self.background_high-self.background_low
        motion=np.uint8(delta>8)*255
        edges=cv2.Canny(gray,25,70)
        edge_distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        moving_edges=edges&cv2.dilate(motion,np.ones((3,3),np.uint8))
        moving_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3)
        self.now=now
        anchors,anchor_info=self._anchors(gray,now,cw,ch)
        seeds=[];flow_accepted=0;self.frame_count+=1
        if all(a is not None for a in anchors) and not scene:
            # Coarse acquisition searches different arc heights, not the full image.
            amplitudes=np.arange(-.30,.561,.025)
            if self.curve is not None and self.confirmed_time is not None and now-self.confirmed_time<=.08 and self.frame_count%15:
                amplitude=(float(anchors[0][1]+anchors[1][1])/2-self.curve[20,1])/ch
                amplitudes=np.clip(amplitude+np.array([-.05,-.025,0,.025,.05]),-.30,.56)
            if self.c.get('whole_shape_model',False) and self.curve is None and self.pending_curve is not None:
                pending=self.pending_curve.copy()
                if self.pending_velocity is not None:pending+=self.pending_velocity*(now-self.pending_time)
                seeds.append((pending,True))
            for amplitude in amplitudes:seeds.append((self._seed(anchors,amplitude,cw,ch),False))
            if self.curve is not None and self.old is not None and self.old_time is not None:
                dt=now-self.old_time
                predicted=self.curve+self.velocity*dt
                previous=self.curve.astype(np.float32).reshape(-1,1,2)
                forward,status,_=cv2.calcOpticalFlowPyrLK(self.old,gray,previous,None,winSize=(15,15),maxLevel=2)
                if forward is not None:
                    back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,self.old,forward,None,winSize=(15,15),maxLevel=2)
                    if back is not None:
                        good=(status.reshape(-1)>0)&(back_status.reshape(-1)>0)&(np.linalg.norm(back.reshape(-1,2)-previous.reshape(-1,2),axis=1)<1.5)
                        good &= np.linalg.norm(forward.reshape(-1,2)-predicted,axis=1)<max(10,ch*.05)
                        if self.seen is not None:good &= now-self.seen<=.08
                        flow_accepted=int(np.count_nonzero(good))
                        # LK points can slide along a textureless rope or lock onto
                        # a blocker. Fit a smooth displacement field; do not insert
                        # each independently tracked point into the curve.
                        if flow_accepted>=6:
                            fu=np.linspace(0,1,41)
                            fb=np.column_stack([np.sin(k*np.pi*fu) for k in range(1,4)])
                            fc=np.linalg.lstsq(np.vstack([fb[good],np.eye(3)*.5]),np.vstack([(forward.reshape(-1,2)-predicted)[good],np.zeros((3,2))]),rcond=None)[0]
                            predicted+=fb@fc
                u=np.linspace(0,1,41)[:,None]
                predicted+=(anchors[0]-predicted[0])[None,:]*(1-u)+(anchors[1]-predicted[-1])[None,:]*u
                seeds.insert(0,(predicted,True))
        self.evidence_cache={}
        self._prepare_evidence(seeds,edge_distance,moving_distance,gray,cw,ch)
        candidates=[]
        for seed,temporal in seeds:
            score,points,observed=self._evidence(seed,edge_distance,moving_distance,gray,cw,ch,temporal)
            if self.curve is not None:score-=min(.12,float(np.mean(np.linalg.norm((points-self.curve)/[cw,ch],axis=1)))*.25)
            candidates.append((score,points,observed,temporal))
        candidates.sort(key=lambda a:a[0],reverse=True)
        # Test the fitted curve, not jagged unsupported edge samples. Try lower-ranked
        # supported fits when the highest scoring background fragment fails.
        fitted=[]
        for candidate in candidates:
            if candidate[0]<.42:break
            candidate_fit=self._fit_candidate(candidate,seeds[0][0] if seeds else None,anchors,anchor_info,cw,ch)
            if candidate_fit is None:continue
            if not self._continuous(candidate_fit[0],now,cw,ch):
                self.continuity_rejections+=1;continue
            fitted.append((candidate,candidate_fit))
        chosen=fitted[0][0] if fitted else None
        if chosen is not None:
            # Reject competing substantially different curves with similar evidence.
            rival=next((a for a,_ in fitted[1:] if np.mean(np.linalg.norm((a[1]-chosen[1])/[cw,ch],axis=1))>.045),None)
            if rival is not None and chosen[0]-rival[0]<.035:chosen=None
        states=[];points=[];observed_points=[];valid=False;coverage=0.0
        fit=fitted[0][1] if chosen is not None else None
        if fit is not None and not self._continuous(fit[0],now,cw,ch):
            self.continuity_rejections+=1;fit=None
        updated_velocity=None
        if fit is not None:
            smooth,detected,observed,coverage=fit
            if self.curve is None:
                dt=None if self.pending_time is None else now-self.pending_time
                self.pending_velocity=None if dt is None else (smooth-self.pending_curve)/dt
                self.pending_curve=smooth.copy();self.pending_time=now;self.pending_count+=1
                self.tracking_status='acquiring'
                if self.pending_count<3:fit=None
                else:
                    self.track_id+=1;self.velocity=np.zeros_like(smooth) if self.pending_velocity is None else self.pending_velocity.copy()
                    self.pending_curve=None;self.pending_time=None;self.pending_velocity=None;self.pending_count=0
            else:
                dt=now-self.old_time;prediction=self.curve+self.velocity*dt
                residual=smooth-prediction
                smooth=prediction+residual*.90
                velocity=self.velocity+residual*(.30/dt)
                units=np.array([cw,ch]);norm=np.linalg.norm(velocity/units,axis=1)
                cap=self.c.get('whole_continuity',{}).get('max_speed',6.0)
                updated_velocity=velocity/np.maximum(1,norm[:,None]/cap)
                observed &= np.linalg.norm(smooth-detected,axis=1)<=max(4,ch*.008)
                coverage=float(np.mean(observed[2:-2]))
                if not self._full_support(observed,anchor_info) and not (chosen[3] and self._partial_allowed() and coverage>=.25):fit=None
            if fit is not None:
                if self.seen is None:self.seen=np.full(41,-1e9)
                self.seen[observed]=now
                self.seen[[0,-1]]=[now if x['source']=='measured' else self.seen[j] for j,x in zip((0,40),anchor_info)]
                states=['measured' if observed[i] or i in (0,40) and anchor_info[0 if i==0 else 1]['source']=='measured' else 'predicted' if now-self.seen[i]<=.12 else 'unknown' for i in range(41)]
                if self.c.get('whole_shape_model',False):states[0]=states[-1]='predicted'
                observed_points=[[float(l+x/cw),float(t+y/ch)] for x,y in detected[observed]]
                if updated_velocity is not None:self.velocity=updated_velocity
                valid=True;self.confirmed_time=now;self.curve=smooth;self.tracking_status='tracking'
                if self._full_support(observed,anchor_info):self.full_confirmed_time=now
                points=[[float(l+x/cw),float(t+y/ch)] for x,y in smooth]
        if not valid:
            if self.curve is not None and self.confirmed_time is not None and now-self.confirmed_time<=.12:
                self.curve=self.curve+self.velocity*(now-self.old_time)
                points=[[float(l+x/cw),float(t+y/ch)] for x,y in self.curve];states=['predicted']*41;self.tracking_status='predicting'
            elif self.curve is not None:
                self.curve=None;self.velocity=None;self.seen=None;self.confirmed_time=None;self.full_confirmed_time=None
                self.pending_curve=None;self.pending_time=None;self.pending_velocity=None;self.pending_count=0;self.center_history.clear();self.tracking_status='lost'
            elif self.pending_time is not None and now-self.pending_time>.08:
                self.pending_curve=None;self.pending_time=None;self.pending_velocity=None;self.pending_count=0
        # No measurement is exposed as accepted when the track was not committed.
        if not valid:observed_points=[]
        center_y=None;speed=None;phase='unavailable';mode='unknown'
        if points:
            center_y=points[20][1]
            if self.center_history and now-self.center_history[-1][0]>.08:self.center_history.clear()
            self.center_history.append((now,center_y))
            recent=list(self.center_history)[-5:]
            if len(recent)>=3 and recent[-1][0]-recent[0][0]>=.025:
                times=np.array([a[0] for a in recent]);values=np.array([a[1] for a in recent])
                fitted,offset=np.polyfit(times-times[-1],values,1)
                error=np.max(np.abs(values-(fitted*(times-times[-1])+offset)))
                if error<.012 and abs(fitted)<4.5:speed=float(fitted)
            phase='descending' if speed is not None and speed>.03 else 'ascending' if speed is not None and speed<-.03 else 'turning'
            mode='rotation_candidate' if min(y for _,y in points)<.40 else 'low_motion_candidate'
        self.old=gray;self.old_time=now
        return dict(valid=False,avatar_valid=False,avatar_y=None,rope_valid=valid,rope_y=center_y if valid else None,rope_points=[],
            track_id=self.track_id,tracking_status=self.tracking_status,continuity_rejections=self.continuity_rejections,continuity_residual=self.last_residual,
            whole_partial=bool(valid and coverage<.45),whole_curve=points,whole_observed_points=observed_points,whole_point_states=states,whole_coverage=coverage,hand_anchors=anchor_info,anchor_constraint='template_or_slot_prior',
            motion_speed=speed,motion_phase=phase,motion_mode_candidate=mode,flow_points=flow_accepted,scene_changed=scene,
            rope_rejection=None if valid else 'whole_curve_not_verified',terminal=None,mode_hint=None,selection_method='whole_shape_model' if self.c.get('whole_shape_model',False) else 'whole_parametric_curve')

class WholeRopeJudgment:
    def __init__(self,config):self.c=config;self.state='observing';self.mode='whole_rope_judgment';self.jumps=0;self.crossings=0
    def reset_motion(self):self.state='recovering'
    def debug_snapshot(self):return dict(input_enabled=False)
    def step(self,o,now,down=False,frame_age=0):
        self.state='stale' if frame_age>self.c['max_frame_age'] else 'tracking' if o['rope_valid'] else 'recovering'
        return dict(down=False,state=self.state,mode=self.mode,input_inhibited='whole_rope_judgment_only',prediction=None,pending=None,
            missing_features=[] if o['rope_valid'] else ['rope'],motion_speed=o.get('motion_speed'))
