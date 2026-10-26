"""Domain-local jump rope composition. No navigation or top-level observation changes."""
import importlib.util
from pathlib import Path

_here = Path(__file__).resolve().parent

def _load(name):
    spec = importlib.util.spec_from_file_location('hololive_'+name, _here/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

JumpRopeVision = _load('jump_rope_vision').JumpRopeVision
JumpRopeController = _load('jump_rope_controller').JumpRopeController

_local_motion=_load("jump_rope_local_motion")
LocalMotionVision=_local_motion.LocalMotionVision
LocalMotionController=_local_motion.LocalMotionController

# Hybrid keeps the established curve/arrow tracker and controller.
import cv2
import numpy as np
import time
from collections import deque

FragmentTracker=_load('jump_rope_fragments').FragmentTracker

class TrajectoryMotionVision(JumpRopeVision):
    def reset(self):
        super().reset()
        self.diff_history=deque(maxlen=3)
        self.active_motion=False
        self.fragments=FragmentTracker()
        self.low_history=deque(maxlen=180)
    def _candidates(self,*args,**kwargs):
        self.motion_mask=self._current_motion_mask
        items=super()._candidates(*args,**kwargs)
        # Motion is a candidate filter, never a jump command. Keep brief turning pauses.
        probe=args[2];index=0 if probe[0]<self.tracked_x else 1
        previous=self.previous[index]
        filtered=[]
        for item in items:
            if item.get('motion') is not None and item['motion']>=.05:
                item['moving_at']=self.last_timestamp;filtered.append(item)
            elif previous is not None and self.last_timestamp-previous.get('moving_at',-1e6)<=.12:
                predicted=previous['y']+previous['velocity']*(self.last_timestamp-previous['time'])
                if abs(item['y']-predicted)<.025:
                    item['moving_at']=previous['moving_at'];filtered.append(item)
        return filtered
    def _select(self,candidates,previous,now):
        chosen=super()._select(candidates,previous,now)
        if chosen is not None:
            index=0 if candidates and chosen['points'][0][0]<self.tracked_x else 1
            self.motion_evidence[index]=chosen.get('moving_at',previous.get('moving_at') if previous else None)
        return chosen
    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        if self.last_timestamp is not None and not 0<now-self.last_timestamp<=self.config['association_max_age']:self.reset()
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        scene=False;self.motion_mask=np.zeros_like(gray)
        if self.diff_history and self.diff_history[0].shape==gray.shape:
            diff=cv2.absdiff(gray,self.diff_history[0])
            scene=np.mean(diff>30)>.45
            if scene:self.previous=[None,None];self.diff_history.clear()
            else:self.motion_mask=cv2.dilate(np.uint8(diff>8)*255,np.ones((3,3),np.uint8))
        self.diff_history.append(gray)
        # Base detect resets its motion mask; install it before candidate extraction.
        mask=self.motion_mask
        self.active_motion=bool(np.any(mask))
        self._current_motion_mask=mask
        self.motion_evidence=[None,None]
        o=super().detect(image,now)
        for index,previous in enumerate(self.previous):
            if previous is not None and self.motion_evidence[index] is not None:previous['moving_at']=self.motion_evidence[index]
        o['scene_changed']=bool(scene)
        if scene or (o['rope_valid'] and (abs(o['rope_slope'])>.9 or abs(o['rope_curvature'])>9)):
            o.update(valid=False,rope_valid=False,rope_y=None,rope_points=[],rope_rejection='scene_or_curve_geometry')
            self.previous=[None,None]
        if scene:self.fragments.reset()
        if not scene and (not o['rope_valid'] or o.get('selection_method')=='fallback'):
            found=self.fragments.detect(gray,mask,self.config,self.tracked_x,now)
            if found:
                use=not o['rope_valid']
                history=self.fragments.full
                if not use and history and now-history['time']<=.12:
                    predicted=history['coef'][2]+history.get('speed',0)*(now-history['time'])
                    use=abs(found['rope_y']-predicted)+.004<abs(o['rope_y']-predicted)
                if use:o.update(found);o['valid']=bool(o['avatar_valid'])
        o['tracked_center_x']=self.tracked_x
        o=self.fragments.accept(o,now)
        if not o['rope_valid'] and o.get('rope_rejection')=='stationary_geometry':self.previous=[None,None]
        if o['rope_valid']:
            self.low_history.append((now,o['rope_y'],o.get('rope_slope') or 0,o.get('rope_curvature') or 0))
        while self.low_history and now-self.low_history[0][0]>1.2:self.low_history.popleft()
        low=list(self.low_history)
        low_candidate=(len(low)>=12 and low[-1][0]-low[0][0]>=.7 and np.max(np.diff([a[0] for a in low]))<=.12
            and min(a[1] for a in low)>.47 and (np.ptp([a[2] for a in low])>.10 or np.ptp([a[3] for a in low])>.8))
        o['motion_mode_candidate']='low_swing' if low_candidate else None
        o['swing_rule_confirmed']=False
        o['motion_fraction']=float(np.mean(mask>0))
        return o
class TrajectoryMotionController(JumpRopeController):
    def __init__(self,config):
        super().__init__(config)
        self.slow_gate=False;self.slow_consumed=False;self.slow_direction=None
        self.low_swing=False;self.overhead_count=0;self.slow_crossed=False
    def debug_snapshot(self):
        d=super().debug_snapshot()
        d.update(low_swing=self.low_swing,slow_pass_consumed=self.slow_consumed,slow_pass_crossed=self.slow_crossed,slow_pass_direction=self.slow_direction)
        return d
    def calibrated(self):
        return False if self.slow_gate else super().calibrated()
    def fit(self):
        full=super().fit()
        if full is not None and full[2]<=.006:return full
        # During acceleration, stale samples must not dominate the next arrival estimate.
        recent=list(self.samples)[-3:]
        if len(recent)<3:return full
        ts=np.array([a[0] for a in recent]);ys=np.array([a[1] for a in recent])
        if ts[-1]-ts[0]<.025 or np.any(np.diff(ts)<=0) or np.max(np.diff(ts))>self.c['max_observation_gap']:return full
        slopes=np.diff(ys)/np.diff(ts)
        if slopes[0]*slopes[1]<=0 or np.max(np.abs(slopes))>4.5:return full
        speed,pos=np.polyfit(ts-ts[-1],ys,1)
        error=float(np.max(np.abs(ys-(speed*(ts-ts[-1])+pos))))
        if error>.006:return full
        return float(pos),float(speed),error
    def step(self,o,now,down=False,frame_age=0):
        # A low-motion mode is geometric evidence, not an instantaneous speed test.
        if o.get('scene_changed'):
            self.low_swing=False;self.overhead_count=0;self.slow_consumed=False;self.slow_crossed=False
        elif o.get('rope_valid'):
            self.overhead_count=self.overhead_count+1 if o['rope_y']<.40 else 0
            if self.overhead_count>=3:
                self.low_swing=False;self.slow_consumed=False;self.slow_crossed=False
            elif o.get('motion_mode_candidate')=='low_swing' or o.get('motion_mode')=='swing':
                self.low_swing=True
        settings=self.c.get('slow_arrival',{})
        danger=settings.get('danger_y',self.c['calibration']['danger_y'])
        # Observe completion even when a previous slow pass is currently moving faster.
        if self.slow_consumed and o.get('rope_valid') and danger is not None:
            passed=(o['rope_y']-danger)*self.slow_direction
            if passed>.004:self.slow_crossed=True
            if passed>settings.get('rearm_distance',.015):
                self.slow_consumed=False;self.slow_crossed=False
        # Require three consistent observations for the experimental visible trigger.
        recent=list(self.samples)[-2:]
        coherent=False
        if o.get('rope_valid') and len(recent)==2:
            ts=np.array([recent[0][0],recent[1][0],now]);ys=np.array([recent[0][1],recent[1][1],o['rope_y']])
            if np.all(np.diff(ts)>0) and np.max(np.diff(ts))<=self.c['max_observation_gap']:
                slopes=np.diff(ys)/np.diff(ts)
                coherent=bool(np.all(slopes>.15) and np.max(slopes)<4.5 and abs(slopes[1]-slopes[0])<=max(.3,abs(float(np.mean(slopes)))*1.2))
        self.c['visible_trial_coherent']=coherent
        slow=None;historical_age=0.0
        minimum=settings.get('min_speed',.03);maximum=settings.get('approach_max_speed',4.5)
        if self.low_swing and o.get('rope_valid') and len(recent)==2 and not o.get('scene_changed'):
            ts=np.array([a[0] for a in recent]+[now]);ys=np.array([a[1] for a in recent]+[o['rope_y']])
            if np.all(np.diff(ts)>0) and np.max(np.diff(ts))<=self.c['max_observation_gap'] and ts[-1]-ts[0]>=.025:
                speed,position=np.polyfit(ts-ts[-1],ys,1)
                error=float(np.max(np.abs(ys-(speed*(ts-ts[-1])+position))))
                slopes=np.diff(ys)/np.diff(ts)
                if minimum<=abs(speed)<=maximum and np.all(slopes*speed>0) and error<=.0035:
                    slow=(float(position),float(speed),error)
        if self.low_swing and slow is None and not o.get('rope_valid') and len(self.samples)>=3 and not o.get('scene_changed'):
            history=list(self.samples)[-3:];age=now-history[-1][0]
            ts=np.array([a[0] for a in history]);ys=np.array([a[1] for a in history])
            if 0<age<=.08 and ts[-1]-ts[0]>=.025 and np.all(np.diff(ts)>0) and np.max(np.diff(ts))<=self.c['max_observation_gap']:
                speed,position=np.polyfit(ts-ts[-1],ys,1)
                error=float(np.max(np.abs(ys-(speed*(ts-ts[-1])+position))))
                if minimum<=abs(speed)<=maximum and np.all(np.diff(ys)*speed>0) and error<=.0035:
                    slow=(float(position+speed*age),float(speed),error);historical_age=age
        # Disable BOTH wide-band trial and ordinary predictive input for slow approaches.
        # Keep the common state machine, landing confirmation and key release intact.
        enabled=self.c.get('demonstration_crossing_trial',False)
        self.slow_gate=self.low_swing
        if self.slow_gate:self.c['demonstration_crossing_trial']=False
        try:d=super().step(o,now,down,frame_age)
        finally:self.c['demonstration_crossing_trial']=enabled;self.slow_gate=False
        if slow is None:
            if self.low_swing:d.update(mode='slow_bidirectional_trial',pending=None,input_inhibited='slow_acquiring_direction')
            return d
        position,speed,error=slow;danger=settings.get('danger_y',self.c['calibration']['danger_y'])
        if danger is None:return d
        direction=1 if speed>0 else -1
        if self.slow_consumed and historical_age==0 and self.slow_crossed and direction!=self.slow_direction:
            self.slow_consumed=False;self.slow_crossed=False
        lead=self.c['calibration']['input_latency_seconds']
        air=self.c['calibration']['safe_airborne_seconds']
        if lead is None or air is None:return d
        lead=settings.get('lead_seconds',min(.12,lead+air*.20))
        eta=(danger-position)/speed
        d.update(mode='slow_bidirectional_trial',motion_speed=speed,
            prediction=dict(eta=eta,arrival=now+eta,speed=speed,error=error,direction=direction,historical=historical_age>0,age=historical_age,rope_y=position,danger_y=danger,lead_seconds=lead),
            pending=now+eta-lead,input_inhibited='slow_waiting_for_feet')
        safe=(not d.get('stop') and not o.get('scene_changed') and frame_age<=self.c['max_frame_age']
            and o.get('avatar_valid') and self.tracking_established and self.ground_count>=self.c['ground_frames']
            and self.jump_sent_at is None and self.c.get('experimental_input',False)
            and not self.slow_consumed and 0<eta<=lead)
        if safe:
            self.slow_consumed=True;self.slow_direction=direction;self.slow_crossed=False
            self.demo_pass_consumed=True;self.consumed=True
            self.jumps+=1;self.jump_sent_at=now;self.release_at=now+self.c['pulse_seconds'];self.state='jump_requested'
            d.update(down=True,state=self.state,jumps=self.jumps,input_inhibited=None,trigger='slow_feet_prediction_trial' if historical_age else 'slow_feet_arrival_trial')
        elif self.slow_consumed:d['input_inhibited']='slow_same_pass_consumed'
        elif self.ground_count<self.c['ground_frames']:d['input_inhibited']='slow_landing_not_confirmed'
        return d

_whole=_load("jump_rope_whole")
WholeRopeVision=_whole.WholeRopeVision
WholeRopeJudgment=_whole.WholeRopeJudgment

# Independent phase route; existing vision/controller implementations stay intact.
_phase=_load("jump_rope_phase")
PhaseRopeVision=_phase.PhaseRopeVision
PhaseRopeJudgment=_phase.PhaseRopeJudgment
_state=_load("jump_rope_phase_state")
PhaseStateVision=_state.PhaseStateVision

_gear=_load("jump_rope_phase_gear")
PhaseGearVision=_gear.gear_vision_type(PhaseStateVision)
