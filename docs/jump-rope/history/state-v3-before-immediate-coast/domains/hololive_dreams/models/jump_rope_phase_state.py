"""Independent v3: three legal motion states, finite swing path and recovery."""
import time
from collections import deque
import numpy as np
import cv2
from modular_agent.realtime.motion_states import LegalSignedTracker,BoundedSwingTracker,BoundedTrajectory


class CandidateChain:
    def __init__(self,cyclic=True):self.cyclic=cyclic;self.records=[]
    def update(self,value,quality,now):
        if quality<.30:
            if self.records and now-self.records[-1][0]>.12:self.records=[]
            return False
        if self.records:
            last=self.records[-1];dt=now-last[0]
            if self.cyclic:value+=round(last[1]-value)
            if dt>.12 or abs(value-last[1])>4*dt+.015:self.records=[]
        self.records.append((now,value,quality));self.records=[r for r in self.records if now-r[0]<=.18][-10:]
        return len(self.records)>=3 and now-self.records[0][0]>=.045
    def slope(self):
        if len(self.records)<3:return None
        t=np.array([r[0] for r in self.records]);v=np.array([r[1] for r in self.records]);t=t-t[-1]
        return float(np.sum((t-t.mean())*(v-v.mean()))/max(1e-9,np.sum((t-t.mean())**2)))


class PhaseStateVision:
    def __init__(self,config,atlas,swing,base_type):
        self.c=config;self.settings=config['phase_parameters'];self.rotation=base_type(config,atlas);self.swing=base_type(config,atlas)
        self.swing_atlas=BoundedTrajectory(swing)
        self.swing.grid=np.linspace(0,1,48)
        self.swing.reference_curves=self.swing_atlas.curves(self.swing.grid)
        self.reset()

    def reset(self):
        self.rotation.reset();self.swing.reset()
        self.rotation.tracker=LegalSignedTracker(1/self.rotation.atlas.period,max_rate=self.settings['max_rate'],max_acceleration=self.settings['max_acceleration'],zero_timeout=self.settings['zero_timeout'])
        self.swing.tracker=BoundedSwingTracker(self.swing_atlas.period,max_rate=self.settings['max_rate'],max_acceleration=self.settings['max_acceleration'],zero_timeout=self.settings['zero_timeout'])
        self.previous=None;self.low=None;self.high=None;self.frame_count=0
        self.motion_state='rotation_forward';self.mode_changes=0;self.enter_direction=1;self.exit_direction_prior=None
        self.low_chain=CandidateChain(False);self.rotation_chain=CandidateChain(True);self.alternative_chain=CandidateChain(True)
        self.low_entry_count=0;self.rotation_exit_count=0;self.rise_history=deque();self.slow_context=None
        self.reacquisitions=0;self.last_reacquire=-1.;self.last_event=None

    @staticmethod
    def _support(vision,curve,raw,seen,observed):
        l,t,_,_=vision.c['roi']
        return seen & (np.linalg.norm((curve-[l,t])*vision.units-raw,axis=1)<=max(4,vision.units[1]*.008)) if observed else np.zeros(41,dtype=bool)

    def _evidence(self,vision,gray,indices):
        options=vision.options[indices];normals=vision.normals[indices];in_bounds=vision.in_bounds[indices];body=vision.body[indices]
        center=vision.sample(gray,options);ridge=np.zeros(center.shape)
        for radius in (3,6,10):
            plus=vision.sample(gray,options+normals[:,:,None,:]*radius)
            minus=vision.sample(gray,options-normals[:,:,None,:]*radius)
            a=center-plus;b=center-minus
            ridge=np.maximum(ridge,np.where(a*b>0,np.minimum(abs(a),abs(b)),0))
        edge_cost=vision.sample(self.distance,options);motion_cost=vision.sample(self.motion_distance,options)
        cost=edge_cost+np.minimum(motion_cost,12)*.20+np.maximum(0,10-ridge)*.50+abs(vision.offsets)[None,None,:]*.1
        cost[~in_bounds]=1e4
        best=np.argmin(cost,axis=2);ii=np.arange(len(indices))[:,None];jj=np.arange(41)[None,:]
        points=options[ii,jj,best]
        seen=(edge_cost[ii,jj,best]<=4)&(ridge[ii,jj,best]>=8)&(vision.sample(self.variation,points)>=8)&(~body)&in_bounds[ii,jj,best]
        seen[:,[0,1,-2,-1]]=False
        moving_seen=seen&(motion_cost[ii,jj,best]<=5)
        coverage=np.mean(seen[:,2:-2],axis=1);motion_fraction=np.mean(moving_seen[:,2:-2],axis=1)
        spans=np.array([(np.ptp(np.flatnonzero(row))/40) if np.count_nonzero(row)>=8 else 0 for row in seen])
        quality=np.clip(coverage*.65+spans*.18+motion_fraction*.20-.008*np.mean(np.minimum(edge_cost[ii,jj,best],12),axis=1),0,1)
        quality[(np.sum(seen,axis=1)<8)|(spans<.40)]=0
        return quality,points,seen,coverage,motion_fraction

    def _select(self,vision,gray,delta,variation,now,global_search=False,upper_only=False):
        predicted=vision.tracker.predict(now)
        gap=vision.grid-predicted
        if vision is self.rotation:gap=(gap+.5)%1-.5
        if global_search or not vision.tracker.locked or self.frame_count%30==0 or vision.tracker.search_wide:
            indices=np.arange(len(vision.grid))
        else:indices=np.flatnonzero(abs(gap)<=min(.5,.06+2*vision.tracker.uncertainty))
        if upper_only:
            eligible=np.flatnonzero(vision.reference_curves[:,20,1]<.33)
            indices=np.intersect1d(indices,eligible)
            if not len(indices):indices=eligible
        if not len(indices):indices=np.array([int(np.argmin(abs(gap)))])
        quality,raw,seen,coverage,moving=self._evidence(vision,gray,indices)
        score=quality.copy()
        if vision.tracker.locked and not global_search:
            penalty=.015 if vision.tracker.search_wide else .06
            radius=.05+vision.tracker.uncertainty
            score-=penalty*np.minimum(9,(gap[indices]/radius)**2)
        choice=int(np.argmax(score))
        # Keep separate non-adjacent alternatives instead of deleting other arcs.
        alternatives=[]
        for candidate in np.argsort(quality)[::-1]:
            position=float(vision.grid[indices[candidate]])
            if not alternatives or all(abs((position-p+.5)%1-.5)>.07 for p in alternatives):alternatives.append(position)
            if len(alternatives)==3:break
        return dict(phase=float(vision.grid[indices[choice]]),quality=float(quality[choice]),raw=raw[choice],seen=seen[choice],
            coverage=float(coverage[choice]),moving=float(moving[choice]),evaluated=len(indices),
            alternatives=alternatives,global_phase=float(vision.grid[indices[int(np.argmax(quality))]]),global_quality=float(max(quality)))

    def _seed(self,tracker,phase,now,direction,rate):
        tracker.reset();tracker.phase=float(phase);tracker.time=now-.001;tracker.locked=True
        tracker.direction=direction;tracker.rate=direction*max(.12,abs(rate));tracker.confidence=.15;tracker.uncertainty=.10
        self.reacquisitions+=1;self.last_reacquire=now

    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        width=self.settings['inference_width'];scale=min(1,width/image.shape[1])
        small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image
        gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if self.previous is not None and self.previous.shape!=gray.shape:self.reset()
        delta=np.zeros_like(gray) if self.previous is None else cv2.absdiff(gray,self.previous)
        scene=bool(np.mean(delta>30)>.45)
        if self.low is None or scene:self.low=gray.astype(float);self.high=self.low.copy()
        else:self.low=np.minimum(gray,self.low+2);self.high=np.maximum(gray,self.high-2)
        self.rotation.prepare(gray);self.swing.prepare(gray);self.frame_count+=1
        edges=cv2.Canny(gray,25,70)
        self.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
        self.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3)
        self.variation=self.high-self.low
        active_swing=self.motion_state=='low_swing'
        if scene:
            for tracker in (self.rotation.tracker,self.swing.tracker):tracker.confidence*=.2;tracker.uncertainty=max(.1,tracker.uncertainty)
            self.low_chain=CandidateChain(False);self.rotation_chain=CandidateChain(True);self.low_entry_count=0;self.rotation_exit_count=0
        rotation=self._select(self.rotation,gray,delta,self.high-self.low,now,global_search=active_swing,upper_only=active_swing)
        q=rotation['quality']
        if scene or not self.rotation.tracker.locked and rotation['moving']<.10:q=0
        # An alternate branch must persist before reacquisition can replace a lost model.
        alternative_ready=self.alternative_chain.update(rotation['global_phase'],rotation['global_quality'],now)
        gap=(rotation['global_phase']-self.rotation.tracker.phase+.5)%1-.5
        if not active_swing and self.rotation.tracker.search_wide and alternative_ready and abs(gap)>.08 and rotation['global_quality']>.65 and now-self.last_reacquire>.30:
            slope=self.alternative_chain.slope();direction=self.rotation.tracker.direction
            if slope is not None and slope*direction>.06:
                self._seed(self.rotation.tracker,rotation['global_phase'],now,direction,slope)
                rotation=self._select(self.rotation,gray,delta,self.high-self.low,now)
                q=rotation['quality'];self.last_event='reacquired_rotation_branch'
        rot_estimate=self.rotation.tracker.update(now,rotation['phase'] if q>=.30 else None,q)
        rot_curve=self.rotation.atlas.curves(rot_estimate['phase'])
        rot_support=self._support(self.rotation,rot_curve,rotation['raw'],rotation['seen'],rot_estimate['observed'])
        rot_valid=bool(np.count_nonzero(rot_support)>=8 and rot_estimate['confidence']>=.20)
        self.rotation.tracker.feedback(np.count_nonzero(rot_support)>=8,now)
        rot_estimate.update(confidence=self.rotation.tracker.confidence,uncertainty=self.rotation.tracker.uncertainty,search_wide=self.rotation.tracker.search_wide)
        y=float(rot_curve[20,1]);self.rise_history.append((now,y,rot_estimate['rate'],rot_valid))
        while self.rise_history and now-self.rise_history[0][0]>.40:self.rise_history.popleft()
        reliable=[r for r in self.rise_history if r[3]]
        rising=len(reliable)>=3 and reliable[-1][1]-reliable[0][1]<-.015
        if rising and abs(rot_estimate['rate'])<.35 and self.slow_context is None:self.slow_context=(now,self.rotation.tracker.direction)
        if self.slow_context and now-self.slow_context[0]>1.2 and not active_swing:self.slow_context=None
        # Swing search is only needed at low height, weak tracking or confirmed swing.
        check_swing=active_swing or self.rotation.tracker.search_wide or self.slow_context is not None or self.frame_count%3==0 and y>.35
        swing=self._select(self.swing,gray,delta,self.high-self.low,now,global_search=not active_swing) if check_swing else None
        swing_estimate=None;swing_curve=None;swing_support=None;swing_valid=False
        if swing:
            low_q=0 if scene or swing['moving']<.03 and not self.swing.tracker.locked else swing['quality']
            low_ready=self.low_chain.update(swing['phase'],low_q,now)
            candidate_low=low_ready and swing['coverage']>=.35 and low_q>=.45
            slow_turn=self.slow_context is not None and abs(rot_estimate['rate'])<.12
            lost_alternative=self.rotation.tracker.search_wide and low_q>rotation['quality']+.12 and swing['moving']>.08
            self.low_entry_count=self.low_entry_count+1 if not active_swing and candidate_low and (slow_turn or lost_alternative) else 0
            if self.low_entry_count>=3:
                self.enter_direction=self.slow_context[1] if self.slow_context else self.rotation.tracker.direction
                slope=self.low_chain.slope();direction=1 if slope is None or slope>=0 else -1
                self._seed(self.swing.tracker,swing['phase'],now,direction,abs(slope or .3))
                self.motion_state='low_swing';active_swing=True;self.mode_changes+=1;self.last_event='entered_low_swing';self.low_entry_count=0
            if active_swing:
                swing_estimate=self.swing.tracker.update(now,swing['phase'] if low_q>=.30 else None,low_q)
                swing_curve=self.swing_atlas.curves(swing_estimate['phase'])
                swing_support=self._support(self.swing,swing_curve,swing['raw'],swing['seen'],swing_estimate['observed'])
                swing_valid=bool(np.count_nonzero(swing_support)>=8 and swing_estimate['confidence']>=.20)
                self.swing.tracker.feedback(np.count_nonzero(swing_support)>=8,now)
                swing_estimate.update(confidence=self.swing.tracker.confidence,uncertainty=self.swing.tracker.uncertainty,search_wide=self.swing.tracker.search_wide)
                rot_ready=self.rotation_chain.update(rotation['phase'],rotation['quality'],now)
                exit_slope=self.rotation_chain.slope()
                exit_evidence=rot_ready and rotation['quality']>max(.50,low_q+.05) and rotation['moving']>.08 and exit_slope is not None and abs(exit_slope)>.20 and self.rotation.atlas.curves(rotation['phase'])[20,1]<.33
                self.rotation_exit_count=self.rotation_exit_count+1 if exit_evidence else 0
                if self.rotation_exit_count>=3:
                    self.exit_direction_prior=-self.enter_direction
                    slope=self.rotation_chain.slope()
                    # The rule is a prior, not proof that the chosen phase branch is correct.
                    # Projection aliases and a false entry must not force a wrong image branch.
                    measured_direction=1 if slope is not None and slope>.20 else -1 if slope is not None and slope<-.20 else self.exit_direction_prior
                    direction=measured_direction if rotation['coverage']>.40 and rotation['moving']>.10 else self.exit_direction_prior
                    self._seed(self.rotation.tracker,rotation['phase'],now,direction,abs(slope or self.rotation.tracker.good_rate))
                    self.motion_state='rotation_forward' if direction>0 else 'rotation_reverse'
                    active_swing=False;self.mode_changes+=1;self.last_event='exited_swing_opposite_direction';self.rotation_exit_count=0;self.slow_context=None
                    # The newly acquired branch is a low-confidence hypothesis this frame.
                    rot_curve=self.rotation.atlas.curves(self.rotation.tracker.phase);rot_support=np.zeros(41,dtype=bool);rot_valid=False
                    rot_estimate.update(phase=self.rotation.tracker.phase%1,phase_unwrapped=self.rotation.tracker.phase,rate=self.rotation.tracker.rate,direction=self.rotation.tracker.direction,confidence=self.rotation.tracker.confidence,uncertainty=self.rotation.tracker.uncertainty,observed=False)
        if active_swing:
            vision=self.swing;estimate=swing_estimate;curve=swing_curve;support=swing_support;valid=swing_valid;candidate=swing
        else:
            self.motion_state='rotation_forward' if self.rotation.tracker.direction>0 else 'rotation_reverse'
            vision=self.rotation;estimate=rot_estimate;curve=rot_curve;support=rot_support;valid=rot_valid;candidate=rotation
        l,t,_,_=self.c['roi'];visible=candidate['raw'][support]/vision.units+[l,t]
        states=['measured' if supported else 'predicted' if estimate['locked'] and estimate['uncertainty']<.12 else 'unknown' for supported in support]
        self.previous=gray
        return dict(valid=False,avatar_valid=False,avatar_y=None,rope_valid=valid,rope_y=float(curve[20,1]) if valid else None,
            rope_points=[],whole_curve=curve.tolist(),whole_point_states=states,whole_observed_points=visible.tolist(),
            whole_coverage=float(np.mean(support[2:-2])),phase_candidate_coverage=candidate['coverage'],hand_anchors=[],
            tracking_status='recovering' if not valid and vision.tracker.search_wide else estimate['status'],track_id=1 if estimate['locked'] else 0,model_exists=True,phase_estimate=estimate,
            phase_visual_quality=candidate['quality'],phase_visual_candidate=candidate['phase'],phase_candidates_evaluated=candidate['evaluated'],
            phase_alternatives=candidate['alternatives'],phase_atlas=self.swing_atlas.name if active_swing else self.rotation.atlas.name,
            phase_supported_mode='three_state_experiment',motion_state=self.motion_state,mode_changes=self.mode_changes,
            mode_candidate='low_swing' if self.low_entry_count else None,entering_rotation_direction=self.enter_direction,
            exit_direction_prior=self.exit_direction_prior,reacquisitions=self.reacquisitions,last_motion_event=self.last_event,
            phase_candidate_moving=candidate['moving'],motion_speed=None,motion_phase='bounded_swing' if active_swing else 'reference_phase',motion_mode_candidate=self.motion_state,
            scene_changed=scene,selection_method='fixed_trajectory_state_v3',rope_rejection=None if valid else 'state_not_visually_verified',terminal=None,mode_hint=None)
