"""Independent fixed-trajectory experiment. It estimates phase, never jump input."""
import time
import cv2
import numpy as np
from modular_agent.realtime.phase_tracking import CyclicTrajectory, PhaseTracker, SignedPhaseTracker


class PhaseRopeVision:
    def __init__(self, config, atlas):
        self.c=config;self.settings=config['phase_parameters'];self.atlas=CyclicTrajectory(atlas)
        self.grid=np.arange(96)/96
        self.reference_curves=self.atlas.curves(self.grid)
        self.reset()

    def reset(self):
        tracker_type=SignedPhaseTracker if self.settings.get('allow_reverse') else PhaseTracker
        self.tracker=tracker_type(1/self.atlas.period,max_rate=self.settings['max_rate'],max_acceleration=self.settings['max_acceleration'])
        self.previous=None;self.geometry=None;self.low=None;self.high=None;self.frame_count=0

    @staticmethod
    def sample(field, points):
        h,w=field.shape;xy=np.rint(points).astype(int)
        return field[np.clip(xy[...,1],0,h-1),np.clip(xy[...,0],0,w-1)].astype(float)

    def prepare(self, gray):
        h,w=gray.shape;l,t,r,b=self.c['roi']
        if self.geometry==gray.shape:return
        self.geometry=gray.shape;self.units=np.array([w/(r-l),h/(b-t)])
        curves=(self.reference_curves-[l,t])*self.units
        tangent=np.gradient(curves,axis=1)
        normals=np.stack([-tangent[:,:,1],tangent[:,:,0]],axis=2)/np.maximum(np.linalg.norm(tangent,axis=2)[:,:,None],1)
        self.normals=normals;self.offsets=np.arange(-5,6)
        self.options=curves[:,:,None,:]+normals[:,:,None,:]*self.offsets[None,None,:,None]
        self.in_bounds=(self.options[...,0]>=0)&(self.options[...,0]<w)&(self.options[...,1]>=0)&(self.options[...,1]<h)
        xx=self.reference_curves[:,:,0];yy=self.reference_curves[:,:,1]
        self.body=np.zeros(xx.shape,dtype=bool)
        for x,width,top,bottom in [(.37,.022,.43,.66),(.47,.02,.40,.63),(.565,.025,.37,.62),(.65,.022,.35,.59),(.73,.022,.33,.57)]:
            self.body|=(abs(xx-x)<width)&(yy>top)&(yy<bottom)

    def evidence(self, gray, delta, variation, indices=None):
        if indices is None:indices=np.arange(len(self.grid))
        options=self.options[indices];normals=self.normals[indices];in_bounds=self.in_bounds[indices];body=self.body[indices]
        edges=cv2.Canny(gray,25,70)
        distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        moving=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
        motion_distance=cv2.distanceTransform(255-moving,cv2.DIST_L2,3)
        center=self.sample(gray,options);ridge=np.zeros(center.shape)
        for radius in (3,6,10):
            plus=self.sample(gray,options+normals[:,:,None,:]*radius)
            minus=self.sample(gray,options-normals[:,:,None,:]*radius)
            a=center-plus;b=center-minus
            ridge=np.maximum(ridge,np.where(a*b>0,np.minimum(abs(a),abs(b)),0))
        edge_cost=self.sample(distance,options);motion_cost=self.sample(motion_distance,options)
        cost=edge_cost+np.minimum(motion_cost,12)*.20+np.maximum(0,10-ridge)*.50+abs(self.offsets)[None,None,:]*.1
        cost[~in_bounds]=1e4
        best=np.argmin(cost,axis=2);ii=np.arange(len(indices))[:,None];jj=np.arange(41)[None,:]
        points=options[ii,jj,best]
        seen=(edge_cost[ii,jj,best]<=4)&(ridge[ii,jj,best]>=8)&(self.sample(variation,points)>=8)&(~body)&in_bounds[ii,jj,best]
        seen[:,[0,1,-2,-1]]=False
        moving_seen=seen&(motion_cost[ii,jj,best]<=5)
        coverage=np.mean(seen[:,2:-2],axis=1);motion_fraction=np.mean(moving_seen[:,2:-2],axis=1)
        spans=np.array([(np.ptp(np.flatnonzero(row))/40) if np.count_nonzero(row)>=8 else 0 for row in seen])
        quality=np.clip(coverage*.65+spans*.18+motion_fraction*.20-.008*np.mean(np.minimum(edge_cost[ii,jj,best],12),axis=1),0,1)
        quality[(np.sum(seen,axis=1)<8)|(spans<.40)]=0
        return quality,points,seen,coverage,motion_fraction

    def detect(self, image, timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        width=self.settings['inference_width'];scale=min(1,width/image.shape[1])
        small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if self.previous is not None and self.previous.shape!=gray.shape:self.reset()
        delta=np.zeros_like(gray) if self.previous is None else cv2.absdiff(gray,self.previous)
        scene=bool(np.mean(delta>30)>.45)
        if self.low is None or scene:self.low=gray.astype(float);self.high=self.low.copy()
        else:self.low=np.minimum(gray,self.low+2);self.high=np.maximum(gray,self.high-2)
        if scene:self.tracker.confidence*=.2;self.tracker.uncertainty=max(.1,self.tracker.uncertainty)
        self.prepare(gray)
        predicted=self.tracker.predict(now)%1
        self.frame_count+=1
        all_gap=(self.grid-predicted+.5)%1-.5
        if self.tracker.locked and self.frame_count%30:
            radius=min(.5,.06+2*self.tracker.uncertainty)
            indices=np.flatnonzero(abs(all_gap)<=radius)
        else:indices=np.arange(len(self.grid))
        quality,raw,seen,coverage,moving=self.evidence(gray,delta,self.high-self.low,indices)
        grid=self.grid[indices]
        gap=(grid-predicted+.5)%1-.5
        if self.tracker.locked:
            radius=.05+self.tracker.uncertainty
            score=quality-.06*np.minimum(9,(gap/radius)**2)
        else:score=quality.copy()
        choice=int(np.argmax(score));q=float(quality[choice])
        # Initial acquisition must have current motion; an old static arc is not proof.
        if scene or not self.tracker.locked and moving[choice]<.10:q=0
        estimate=self.tracker.update(now,float(grid[choice]) if q>=.30 else None,q)
        curve=self.atlas.curves(estimate['phase'])
        l,t,_,_=self.c['roi']
        supported=seen[choice] if estimate['observed'] else np.zeros(41,dtype=bool)
        # A chosen template far from the retained hypothesis is not a measured point.
        if abs((grid[choice]-estimate['phase']+.5)%1-.5)>.04:supported=np.zeros(41,dtype=bool)
        supported &= np.linalg.norm((curve-[l,t])*self.units-raw[choice],axis=1)<=max(4,self.units[1]*.008)
        states=['measured' if flag else 'predicted' if estimate['locked'] and estimate['uncertainty']<.12 else 'unknown' for flag in supported]
        l,t,_,_=self.c['roi'];visible=raw[choice][supported]/self.units+[l,t]
        valid=bool(estimate['observed'] and np.count_nonzero(supported)>=8 and estimate['confidence']>=.20)
        self.previous=gray
        return dict(valid=False,avatar_valid=False,avatar_y=None,rope_valid=valid,rope_y=float(curve[20,1]) if valid else None,
            rope_points=[],whole_curve=curve.tolist(),whole_point_states=states,whole_observed_points=visible.tolist(),
            whole_coverage=float(np.mean(supported[2:-2])),phase_candidate_coverage=float(coverage[choice]),hand_anchors=[],
            tracking_status=estimate['status'],track_id=1 if estimate['locked'] else 0,model_exists=True,
            phase_estimate=estimate,phase_visual_quality=q,phase_visual_candidate=float(grid[choice]),phase_candidates_evaluated=len(indices),
            phase_atlas=self.atlas.name,phase_supported_mode='rotation_only',motion_speed=None,
            motion_phase='reference_phase',motion_mode_candidate='rotation_reference',
            scene_changed=scene,selection_method='fixed_trajectory_signed_v2' if self.settings.get('allow_reverse') else 'fixed_trajectory_phase_v1',
            rope_rejection=None if valid else 'phase_not_visually_verified',terminal=None,mode_hint=None)


class PhaseRopeJudgment:
    def __init__(self,config):self.c=config;self.state='acquiring';self.mode='phase_judgment';self.jumps=0
    def reset_motion(self):self.state='acquiring'
    def debug_snapshot(self):return dict(input_enabled=False)
    def step(self,o,now,down=False,frame_age=0):
        self.state='stale' if frame_age>self.c['max_frame_age'] else o['tracking_status']
        return dict(down=False,state=self.state,mode=self.mode,input_inhibited='phase_judgment_only',prediction=None,pending=None,
            missing_features=[] if o['rope_valid'] else ['visual_phase'],motion_speed=None)
