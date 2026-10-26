"""North-up visual camera steering; keyboard movement is W only."""
from dataclasses import dataclass
import math
import cv2
import numpy as np
from .navigation_planner import RouteFollower,clear_line
from .patrol import Decision
from .motion_dynamics import camera_headings


def angle_error(target,current):return (target-current+180)%360-180


@dataclass(frozen=True)
class CameraHeading:
    degrees:float
    t:float
    valid:bool=False
    source:str='unknown'
    confidence:float=0


@dataclass(frozen=True)
class CameraTurn:
    kind:str='turn'
    reason:str='align_camera'
    keys:tuple=()
    duration:float=0
    target:tuple|None=None
    mouse_dx:int=0
    counts_per_second:int=240


@dataclass(frozen=True)
class CruiseDecision:
    kind:str='cruise'
    reason:str='continuous_w_visual_steering'
    keys:tuple=('w',)
    duration:float=.5
    target:tuple|None=None
    mouse_dx:int=0
    counts_per_second:int=240


def reference_cone(patch,background,coverage,half_angle=46):
    """Fit a sector relative to clean mapped terrain, with two free colour levels."""
    patch=cv2.resize(patch,(164,164)).astype(np.float32)
    background=cv2.resize(background,(164,164)).astype(np.float32)
    coverage=cv2.resize(coverage,(164,164),interpolation=cv2.INTER_NEAREST)>250
    yy,xx=np.mgrid[:164,:164];radius=np.hypot(xx-82,yy-82)
    bins=np.rint(np.rad2deg(np.arctan2(yy-82,xx-82))/2).astype(int)%180
    valid=(radius>32)&(radius<65)&coverage
    if valid.sum()<1500:return None,0
    residual=(patch[:,:,2]-patch[:,:,0]-background[:,:,2]+background[:,:,0])/np.maximum(35,160-background[:,:,2]+background[:,:,0])
    weights=np.bincount(bins[valid],minlength=180).astype(np.float32)
    profile=np.asarray([np.median(residual[valid&(bins==b)]) if weights[b] else 0 for b in range(180)],np.float32)
    templates=(np.abs((np.arange(180)[None,:]*2-np.arange(360)[:,None]+180)%360-180)<=half_angle).astype(np.float32)
    inside_count=templates@weights;total=float(weights.sum());outside_count=total-inside_count
    values=profile*weights;inside=templates@values;all_values=float(values.sum())
    variance=float((profile*profile*weights).sum()-all_values**2/total)
    if variance<.05:return None,0
    gain=inside/np.maximum(inside_count,1)-(all_values-inside)/np.maximum(outside_count,1)
    loss=(profile*profile*weights).sum()-inside**2/np.maximum(inside_count,1)-(all_values-inside)**2/np.maximum(outside_count,1)
    loss[(gain<.035)|(inside_count<total*.12)|(outside_count<total*.25)]=np.inf
    heading=int(np.argmin(loss))
    if not np.isfinite(loss[heading]):return None,0
    explained=1-float(loss[heading])/variance
    distant=np.abs((np.arange(360)-heading+180)%360-180)>=20
    margin=(float(np.min(loss[distant]))-float(loss[heading]))/variance
    if explained<.60 or margin<.08:return None,explained
    return float(heading),explained


def paired_cone(previous,current,previous_heading,half_angle=46):
    """Track both signed moving boundaries against the same stationary terrain.

    Unlike a short-history temporal minimum, this never estimates sector width
    from one visible edge. The previous absolute visual heading anchors the fit.
    """
    old=cv2.resize(previous,(164,164)).astype(np.float32)
    new=cv2.resize(current,(164,164)).astype(np.float32)
    yy,xx=np.mgrid[:164,:164];radius=np.hypot(xx-82,yy-82)
    valid=(radius>33)&(radius<66)
    bins=np.rint(np.rad2deg(np.arctan2(yy-82,xx-82))/2).astype(int)%180
    residual=(new[:,:,2]-new[:,:,0]-old[:,:,2]+old[:,:,0])/np.maximum(35,160-old[:,:,2]+old[:,:,0])
    weights=np.bincount(bins[valid],minlength=180).astype(np.float32)
    profile=np.asarray([np.median(residual[valid&(bins==b)]) for b in range(180)],np.float32)
    sector=lambda headings:(np.abs((np.arange(180)[None,:]*2-np.asarray(headings)[:,None]+180)%360-180)<=half_angle).astype(np.float32)
    templates=sector(np.arange(360))-sector([previous_heading])
    energy=float((profile**2*weights).sum())
    if energy<.1:return None,0
    norm=(templates**2)@weights;dot=templates@(profile*weights)
    gain=dot/np.maximum(norm,1)
    loss=energy-dot**2/np.maximum(norm,1)
    positive=(templates>0)@weights;negative=(templates<0)@weights
    loss[(gain<.035)|(positive<60)|(negative<60)]=np.inf
    index=int(np.argmin(loss))
    if not np.isfinite(loss[index]):return None,0
    confidence=1-float(loss[index])/energy
    rivals=np.abs((np.arange(360)-index+180)%360-180)>=15
    margin=(float(np.min(loss[rivals]))-float(loss[index]))/energy
    if confidence<.65 or margin<.10:return None,confidence
    return float(index),confidence


class VisualCameraHeading:
    def __init__(self,reference,coverage=None):
        self.reference=reference;self.coverage=coverage if coverage is not None else np.full(reference.shape[:2],255,np.uint8)
        self.history=[];self.anchor=None;self.pending=None;self.good=0
        self.last_good=None;self.expected=None
        self.diagnostics={}

    def expect_rotation(self,count,degrees_per_count,t):
        # Prediction only rejects impossible visual estimates; it never creates
        # a valid camera observation or permission to walk.
        if self.last_good is not None:
            self.expected=((self.last_good[1]+count*degrees_per_count)%360,t,abs(count*degrees_per_count))

    def apply_mouse_delta(self,count,degrees_per_count):
        if self.expected is not None:
            angle,stamp,rotation=self.expected;delta=count*degrees_per_count
            self.expected=((angle+delta)%360,stamp,rotation+abs(delta))

    def read(self,patch,position,t):
        self.diagnostics={}
        if not position.valid or not 0<=t-position.t<=.5:
            self.good=0;return CameraHeading(0,t)
        xy=(position.x,position.y)
        if self.anchor is None or math.dist(xy,self.anchor)>1.5:
            self.history=[];self.anchor=xy;self.last_good=None
        self.history.append(patch.copy());self.history=self.history[-24:]
        h,w=self.reference.shape[:2];degree=None;confidence=0;source='reference_cone'
        if 0<=xy[0]<w and 0<=xy[1]<h:
            center=(float(xy[0]-.5),float(xy[1]-.5))
            background=cv2.getRectSubPix(self.reference,(164,164),center)
            known=cv2.getRectSubPix(self.coverage,(164,164),center)
            # getRectSubPix repeats borders; repeated pixels must stay UNKNOWN.
            yy,xx=np.mgrid[:164,:164]
            known[(xx+xy[0]-82<0)|(xx+xy[0]-82>=w)|(yy+xy[1]-82<0)|(yy+xy[1]-82>=h)]=0
            degree,confidence=reference_cone(patch,background,known)
            self.diagnostics['reference']=dict(degrees=degree,confidence=confidence)
        if self.last_good is not None:
            old,old_heading,old_t=self.last_good
            tracked,tracked_confidence=paired_cone(old,patch,old_heading)
            self.diagnostics['paired']=dict(degrees=tracked,confidence=tracked_confidence,baseline=old_heading)
            if tracked is not None:
                plausible=True
                if self.expected is not None:
                    predicted,sent_t,rotation=self.expected
                    if 0<=t-sent_t<=1.5:plausible=abs(angle_error(tracked,predicted))<=max(12,rotation*.35)
                if plausible:degree=tracked;confidence=tracked_confidence;source='paired_boundary_cone'
        # Short temporal histories are only a fallback, never an unsolicited
        # replacement for a valid map-relative or paired-boundary observation.
        if degree is None and len(self.history)>=8:
            directions,quality=camera_headings(self.history,half_angle=46)
            if directions[-1] is not None:
                degree=directions[-1];confidence=1-quality[-1]['fit_mse'];source='stationary_temporal_cone'
        if degree is None:self.good=0;return CameraHeading(0,t)
        if self.expected is not None:
            predicted,sent_t,rotation=self.expected
            self.diagnostics['prediction']=dict(degrees=predicted,rotation=rotation,age=t-sent_t)
            if 0<=t-sent_t<=1.5:
                if abs(angle_error(degree,predicted))>max(12,rotation*.35):
                    self.good=0;return CameraHeading(degree,t,False,'cone_prediction_disagreement',confidence)
            elif t-sent_t>1.5:self.expected=None
        if source=='stationary_temporal_cone' and self.last_good is not None:
            predicted_turn=self.expected is not None and 0<=t-self.expected[1]<=1.5
            if not predicted_turn and abs(angle_error(degree,self.last_good[1]))>12:
                self.good=0;return CameraHeading(degree,t,False,'temporal_cone_ambiguous',confidence)
        if self.pending is not None:
            old,old_t=self.pending
            self.good=self.good+1 if abs(angle_error(degree,old))<=max(8,30*(t-old_t)+5) else 1
        else:self.good=1
        self.pending=(degree,t)
        if self.good>=2:self.last_good=(patch.copy(),degree,t)
        return CameraHeading(degree,t,self.good>=2,source,confidence)


class CameraWRouteFollower(RouteFollower):
    """Visual W/mouse control; live progress-first or legacy diagnostic mode."""
    def __init__(self,plan,mask,*,degrees_per_count,speed=28.5,stop_distance=6,continuous=False,fast_turns=False,progress_first=False):
        super().__init__(plan,mask)
        if any(s['kind']=='jump' and not s.get('verified') for s in plan['segments']):raise ValueError('自动跳跃需要已验证的有向连接')
        if not math.isfinite(degrees_per_count) or not .005<=abs(degrees_per_count)<=2:raise ValueError('镜头标定无效')
        if not math.isfinite(speed) or not 2<=speed<=180 or not math.isfinite(stop_distance) or not 0<=stop_distance<=20:raise ValueError('W参数无效')
        self.degrees_per_count=degrees_per_count;self.speed=speed;self.stop_distance=stop_distance
        self.reason=None;self.sent=0;self.ready_at=0;self.settling=True;self.stable_xy=None;self.stable_at=None
        self.last_heading=None;self.unknown_since=None;self.pending_turn=None;self.jump_at=None
        self.waypoint_index=0;self.waypoint_at=None;self.arrivals=0;self.last_xy=None;self.last_progress=None;self.move_started=None
        self.continuous=continuous;self.cruising=False;self.steering_check=None
        self.fast_turns=fast_turns;self.last_heading_source=None;self.last_heading_t=None
        self.progress_first=progress_first

    def stop(self,reason):self.reason=reason;return Decision('stop',reason)

    def dispatched(self,decision,now):
        self.sent+=1
        if decision.kind=='cruise':
            self.cruising=True;self.settling=False;self.ready_at=now
            if self.move_started is None:self.move_started=now;self.last_progress=now
            if not self.progress_first and abs(decision.mouse_dx*self.degrees_per_count)>1 and self.steering_check is None:
                self.steering_check=(self.last_heading,now,decision.mouse_dx)
        elif decision.kind=='turn':
            self.pending_turn=dict(heading=self.last_heading,source=self.last_heading_source,
                                   observed_t=self.last_heading_t,expected=decision.mouse_dx*self.degrees_per_count,t=now)
            self.ready_at=now+.06
        elif decision.kind in ('move','jump'):
            self.cruising=False
            if decision.kind=='jump' and decision.reason!='remembered_space':self.jump_at=now
            coast=.25 if decision.reason=='w_approach_with_stop_reserve' else .60
            self.ready_at=now+(.10 if self.jump_at is not None else coast)
            self.settling=self.jump_at is None;self.stable_xy=None;self.stable_at=None
            if self.move_started is None:self.move_started=now;self.last_progress=now

    def brake(self,now,reason):
        self.cruising=False;self.steering_check=None
        self.settling=True;self.ready_at=now+.25;self.stable_xy=None;self.stable_at=None
        return Decision('wait',reason)

    def step(self,position,frame_id,now,*,heading=None,free_scene=True,cancelled=False):
        if self.reason:return self.stop(self.reason)
        if cancelled:return self.stop('cancelled')
        if not free_scene:return self.stop('free_scene_lost')
        if self.sent>=5000:return self.stop('input_budget_exhausted')
        if self.index>=len(self.actions):return self.stop('route_traversed_collection_unverified')
        if position is None or not position.valid or not 0<=now-position.t<=.5 or frame_id<=self.last_frame:
            if self.cruising:return self.brake(now,'cruise_localization_lost_brake')
            self.arrivals=0;self.landing_frames=0;return Decision('wait','fresh_localization_required')
        self.last_frame=frame_id;xy=(position.x,position.y)
        if not all(math.isfinite(v) for v in xy):return self.stop('invalid_position')
        if self.index!=self.waypoint_index:
            self.waypoint_index=self.index;self.waypoint_at=now;self.move_started=None;self.last_progress=now
        if self.waypoint_at is None:self.waypoint_at=now
        if now-self.waypoint_at>60:return self.stop('waypoint_timeout')
        if self.last_xy is None or math.dist(xy,self.last_xy)>=2:self.last_xy=xy;self.last_progress=now
        if self.move_started is not None and now-self.last_progress>5:return self.stop('stuck_no_visual_progress')
        if now<self.ready_at:return Decision('wait','coasting' if self.settling else 'input_response_wait')
        if self.settling:
            if self.stable_xy is None or math.dist(xy,self.stable_xy)>2:self.stable_xy=xy;self.stable_at=now
            if now-self.stable_at<.10:return Decision('wait','confirming_stop_before_turn')
            self.settling=False
        action=self.actions[self.index];target=tuple(action['target']);distance=math.dist(xy,target)
        # Shorten the lease according to remaining distance rather than stopping
        # half a second early at every observation. Account for recognition age.
        pose_age=max(0,now-position.t)
        brake_distance=3+self.stop_distance+self.speed*(pose_age+.08)
        if self.cruising and distance<=brake_distance:return self.brake(now,'cruise_brake_for_waypoint')
        if action['kind']=='walk' and distance<=3:
            self.arrivals+=1
            if self.arrivals>=2:self.index+=1;self.arrivals=0
            return Decision('wait','waypoint_observed' if not self.arrivals else 'confirming_waypoint',target=target)
        self.arrivals=0
        if self.jump_at is not None:
            if now-self.jump_at>2:return self.stop('jump_landing_timeout_no_retry')
            self.landing_frames=self.landing_frames+1 if distance<=3 and now-self.jump_at>=.5 else 0
            if self.landing_frames>=2:
                self.index+=1;self.jump_at=None;self.landing_frames=0;self.settling=True;self.ready_at=now+.6
                return Decision('wait','jump_landing_position_observed',target=target)
            start=action['start'];delta=np.asarray(target)-start;length=max(float(np.linalg.norm(delta)),.001)
            along=float((np.asarray(xy)-start)@delta/length)
            cross=abs((xy[0]-start[0])*delta[1]-(xy[1]-start[1])*delta[0])/length
            if cross>8 or not -4<=along<=length+4:return self.stop('jump_left_corridor')
            if distance<=3:return Decision('wait','confirming_landing_position',target=target)
        if heading is None or not heading.valid or not math.isfinite(heading.degrees) or not 0<=now-heading.t<=.5:
            if self.cruising:return self.brake(now,'cruise_heading_lost_brake')
            if self.unknown_since is None:self.unknown_since=now
            if now-self.unknown_since>8:return self.stop('camera_heading_unavailable')
            if self.jump_at is not None:return Decision('wait','camera_heading_required_in_jump')
            if self.pending_turn is not None:
                if now-self.pending_turn['t']>(.35 if self.pending_turn['heading'] is None else 1.2):self.pending_turn=None
                return Decision('wait','camera_turn_response_wait')
            self.last_heading=None
            count=round(20/abs(self.degrees_per_count)) if self.fast_turns else 48
            rate=7200 if self.fast_turns else 240
            return CameraTurn(reason='observe_cone_with_stationary_sweep',duration=abs(count)/rate,target=target,mouse_dx=count,counts_per_second=rate)
        self.unknown_since=None;self.last_heading=heading.degrees
        self.last_heading_source=heading.source;self.last_heading_t=heading.t
        if self.pending_turn is not None:
            pending=self.pending_turn
            if self.progress_first:
                if heading.t<pending['t']:return Decision('wait','fresh_camera_response_required')
                # Fresh visual feedback is the next control state, not a
                # pass/fail test against one delayed mouse command.
                self.pending_turn=None
        if self.pending_turn is not None:
            pending=self.pending_turn
            if pending.get('source') is not None and heading.source!=pending['source']:
                # Absolute estimates from different sensors are not a measured
                # response to the same mouse command. Reobserve while stopped.
                self.pending_turn=None;self.steering_check=None
                return Decision('wait','camera_heading_source_changed_reobserve')
            if pending.get('observed_t') is not None and heading.t<=pending['observed_t']:
                return Decision('wait','fresh_camera_response_required')
            if pending['heading'] is not None:
                changed=angle_error(heading.degrees,pending['heading'])
                if abs(changed)<.3:
                    if now-pending['t']>1:return self.stop('camera_turn_not_observed')
                    return Decision('wait','camera_turn_response_wait')
                if changed*pending['expected']<0 and abs(changed)>2:return self.stop('camera_turn_direction_mismatch')
                if abs(changed-pending['expected'])>max(5,abs(pending['expected'])*.8):return self.stop('camera_turn_response_mismatch')
            self.pending_turn=None
        desired=math.degrees(math.atan2(target[1]-xy[1],target[0]-xy[0]))%360
        error=angle_error(desired,heading.degrees)
        moving_limit=45 if self.progress_first else 18
        starting_limit=30 if self.progress_first else 6
        if self.continuous and action['kind']=='walk' and distance>brake_distance and abs(error)<=(moving_limit if self.cruising else starting_limit):
            if not clear_line(self.mask,xy,target):return self.stop('current_position_requires_replan')
            lease=min(.5,(distance-3-self.stop_distance)/self.speed-pose_age)
            horizon=self.speed*min(.5,pose_age+lease)+self.stop_distance
            for bearing in (heading.degrees,desired,heading.degrees+error*.5):
                theta=math.radians(bearing)
                predicted=(xy[0]+math.cos(theta)*horizon,xy[1]+math.sin(theta)*horizon)
                if not clear_line(self.mask,xy,predicted):
                    if self.cruising:return self.brake(now,'cruise_corridor_requires_brake')
                    break
            else:
                if self.steering_check is not None and self.progress_first:self.steering_check=None
                if self.steering_check is not None and heading.source!='input_prediction_bridge':
                    before,started,count=self.steering_check
                    changed=angle_error(heading.degrees,before)
                    if abs(changed)>1:
                        if changed*count*self.degrees_per_count<0:return self.stop('camera_turn_direction_mismatch')
                        self.steering_check=None
                    elif now-started>1:return self.stop('camera_turn_not_observed')
                limit=360 if self.progress_first else 72
                count=0 if abs(error)<=2 else int(np.clip(round(error/self.degrees_per_count*.65),-limit,limit))
                return CruiseDecision(target=target,mouse_dx=count,duration=lease,counts_per_second=2400 if self.progress_first else 240)
        if self.cruising:return self.brake(now,'cruise_brake_before_alignment')
        if abs(error)>6:
            if self.jump_at is not None:return self.stop('jump_heading_lost')
            limit=min(3600,round(120/abs(self.degrees_per_count))) if self.fast_turns else 72
            count=int(np.clip(round(error/self.degrees_per_count*.85),-limit,limit))
            rate=7200 if self.fast_turns else 240
            return CameraTurn(duration=abs(count)/rate,target=target,mouse_dx=count,counts_per_second=rate)
        if action['kind']=='jump' and self.jump_at is None:
            if math.dist(xy,action['start'])>3:return self.stop('jump_start_not_reached')
            return Decision('jump','camera_aligned_w_jump',('w','space'),.12,target)
        if self.jump_at is not None:return Decision('move','w_only_jump_correction',('w',),.12,target)
        if not clear_line(self.mask,xy,target):return self.stop('current_position_requires_replan')
        available=distance-3-self.stop_distance
        duration=min(.30,max(.08,available/self.speed)) if available>2 else min(.12,max(.08,(distance-3)*.5/self.speed))
        theta=math.radians(heading.degrees);travel=self.speed*duration+min(self.stop_distance,self.speed*duration)
        predicted=(xy[0]+math.cos(theta)*travel,xy[1]+math.sin(theta)*travel)
        if not clear_line(self.mask,xy,predicted):return self.stop('w_coast_would_leave_walkable_area')
        return Decision('move','w_approach_with_stop_reserve' if available>2 else 'w_fine_approach',('w',),duration,target)
