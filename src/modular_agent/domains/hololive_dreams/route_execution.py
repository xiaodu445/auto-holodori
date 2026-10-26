"""Bounded visual route execution; no dead-reckoning position updates."""
import math
import numpy as np
from .navigation_planner import RouteFollower
from .patrol import Decision
from .patrol import MotionCalibration


class MotionProbe:
    """Four bounded probes, each requiring a 40px annotated clear disk."""
    def __init__(self,mask):
        self.mask=mask;self.motion=MotionCalibration();self.pending=None;self.rows=[]

    def step(self,position,now):
        if not position.valid or not 0<=now-position.t<=.5:return Decision('wait','calibration_needs_position')
        if self.pending:
            key,before,sent=self.pending
            if now-sent>1:raise ValueError('标定观察超时，请重新启动')
            if now-sent<.4:return Decision('wait','calibration_settling')
            self.motion.add_sample(key,before,position,.15)
            if math.hypot(*self.motion.vectors[key])>180:raise ValueError('标定速度超过安全探测包络')
            self.rows.append(dict(key=key,held_seconds=.15,before=before.__dict__,after=position.__dict__))
            self.pending=None
        if len(self.rows)==4:
            self.motion.validate();return Decision('stop','calibration_complete')
        x,y=round(position.x),round(position.y);h,w=self.mask.shape
        if not (40<=x<w-40 and 40<=y<h-40):raise ValueError('标定需要距离地图边缘40像素的开阔区域')
        yy,xx=np.ogrid[-40:41,-40:41]
        if not np.all(self.mask[y-40:y+41,x-40:x+41][xx*xx+yy*yy<=1600]):
            raise ValueError('请将角色移到标注可走区内、半径40像素无障碍的开阔处再启动')
        return Decision('move','calibration_probe',('wasd'[len(self.rows)],),.15)

    def dispatched(self,decision,position,now):
        self.pending=(decision.keys[0],position,now)


class AutoRouteFollower(RouteFollower):
    def __init__(self, plan, mask, calibration):
        calibration.validate()
        super().__init__(plan, mask, calibration)
        # Near a 3px waypoint the old 25ms floor could reject every direction.
        # Allow fine correction instead of falsely reporting an unreachable goal.
        self.settings.min_pulse=.005
        jumps = [s for s in plan['segments'] if s['kind']=='jump']
        if any(not s.get('verified') for s in jumps):
            raise ValueError('自动跳跃需要重新规划，并使用人工验证的跳跃连接')
        self.reason = None
        self.progress_at = None
        self.progress_xy = None
        self.action_index = 0
        self.jump_at = None
        self.sent = 0
        self.ready_at = 0
        self.waypoint_at = None

    def stop(self, reason):
        self.reason = reason
        return Decision('stop', reason)

    def dispatched(self, decision, now):
        self.sent += 1
        self.ready_at = now + .12
        if decision.kind=='jump':self.jump_at = now

    def step(self, position, frame_id, now, *, free_scene=True, cancelled=False):
        if self.reason:return self.stop(self.reason)
        if cancelled:return self.stop('cancelled')
        if self.sent>=5000:return self.stop('input_budget_exhausted')
        if now<self.ready_at:return Decision('wait','settling')
        if not free_scene:return self.stop('free_scene_lost')
        if position is None or not position.valid or not 0<=now-position.t<=.5:
            self.landing_frames=0
            return Decision('wait','fresh_localization_required')
        if frame_id<=self.last_frame:return Decision('wait','fresh_localization_required')
        xy = (position.x,position.y)
        if not all(math.isfinite(v) for v in xy):return self.stop('invalid_position')
        if self.index!=self.action_index:
            self.action_index=self.index;self.progress_at=now;self.progress_xy=xy;self.waypoint_at=now
        if self.waypoint_at is None:self.waypoint_at=now
        if now-self.waypoint_at>40:return self.stop('waypoint_timeout')
        if self.progress_at is None or math.dist(xy,self.progress_xy)>=2:
            self.progress_at=now;self.progress_xy=xy
        if now-self.progress_at>4:return self.stop('stuck_no_visual_progress')
        if self.index>=len(self.actions):return self.stop('route_traversed_collection_unverified')
        action=self.actions[self.index]
        if action['kind']!='jump':
            decision=super().step(position,frame_id,now,free_scene=free_scene)
            if decision.reason in ('current_position_requires_replan','pulse_would_leave_walkable_area','motion_cannot_reduce_error'):
                return self.stop(decision.reason)
            return decision
        self.last_frame=frame_id
        target=tuple(action['target'])
        if self.jump_at is None:
            if math.dist(xy,action['start'])>3:return self.stop('jump_start_not_reached')
            pulse=self.motion.pulse((target[0]-xy[0],target[1]-xy[1]),self.settings)
            if not pulse:return self.stop('jump_direction_unavailable')
            return Decision('jump','directed_jump_takeoff',pulse[0]+('space',),.12,target)
        elapsed=now-self.jump_at
        if elapsed>2:return self.stop('jump_landing_timeout_no_retry')
        self.landing_frames=self.landing_frames+1 if math.dist(xy,target)<=3 and elapsed>=.5 else 0
        if self.landing_frames>=2:
            self.index+=1;self.jump_at=None;self.landing_frames=0
            return Decision('wait','jump_landing_position_observed',target=target)
        # Only move inside the directed jump corridor, never re-press Space.
        start=action['start'];dx=target[0]-start[0];dy=target[1]-start[1]
        length=max(math.hypot(dx,dy),.001)
        along=((xy[0]-start[0])*dx+(xy[1]-start[1])*dy)/length
        cross=abs((xy[0]-start[0])*dy-(xy[1]-start[1])*dx)/length
        if cross>8 or not -4<=along<=length+4:return self.stop('jump_left_corridor')
        if math.dist(xy,target)<=3:return Decision('wait','confirming_landing_position',target=target)
        pulse=self.motion.pulse((target[0]-xy[0],target[1]-xy[1]),self.settings)
        if not pulse:return self.stop('jump_direction_unavailable')
        return Decision('move','jump_direction_correction',pulse[0],pulse[1],target)
