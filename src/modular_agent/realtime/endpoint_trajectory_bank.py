"""Independent endpoint-transition experiment; preserves the original C4 bank."""
import math
import numpy as np
from modular_agent.realtime.trajectory_bank import TrajectoryBank

class EndpointTrajectoryBank(TrajectoryBank):
    def __init__(self,settings,rotation,swing):
        curves=rotation.curves(np.arange(2048)/2048);front=float(np.argmax(curves[:,20,1])/2048)
        rear_curve=swing.curves(0.)
        errors=np.mean(np.linalg.norm(curves-rear_curve,axis=2),axis=1)
        mask=(np.arange(2048)/2048>front+.10)&(np.arange(2048)/2048<.96)
        rear=float(np.argmin(np.where(mask,errors,np.inf))/2048)
        self.normal_pose={1:rear,-1:front}
        super().__init__(settings,front,.5)
        self.low_starts={1:0.,-1:self.warp.inverse(.5)}
        self.low_exits={1:self.warp.inverse(.5),-1:0.}
        minimum=settings.get('minimum_swing_cycles',2.)
        if type(minimum) not in (int,float) or not math.isfinite(minimum) or not 0<=minimum<=3.:raise ValueError('invalid minimum_swing_cycles')
    def reset(self):
        super().reset();self.low_phase_travel=0.;self.low_phase_previous=None
    def ground_boundary(self,item):
        return self.low_exits[item.origin] if item.mode=='low_swing' else self.normal_pose[item.direction]
    def commit_episode(self,active,best):
        super().commit_episode(active,best)
        if best.mode=='low_swing':self.low_phase_travel=0.;self.low_phase_previous=best.phase
    def choose(self,now,dt,compatible=None):
        if not self.items:return None
        active=next(p for p in self.items if p.key==self.active)
        if active.mode=='low_swing':
            if self.low_phase_previous is not None:self.low_phase_travel+=max(0.,active.phase-self.low_phase_previous)
            self.low_phase_previous=active.phase
        selected=super().choose(now,dt,compatible)
        if selected.mode=='low_swing':self.low_phase_previous=selected.phase
        return selected
    def legal_successor(self,active,p,now):
        if active.mode=='low_swing' and p.mode!=active.mode and self.low_phase_travel<self.c.get('minimum_swing_cycles',2.) and not p.recovered_exit:return False
        return super().legal_successor(active,p,now)

    def advance(self,now):
        if not math.isfinite(now) or self.time is not None and now<=self.time:raise ValueError('nonmonotonic playback clock')
        dt=0. if self.time is None else now-self.time;self.time=now;self.event=None
        branches=[]
        committed=next((p for p in self.items if p.key==self.active),None)
        if committed is not None and committed.mode=='low_swing':self.low_played_cycles+=committed.speed*dt
        elif committed is not None and not self.rotation_rearmed:self.rearm_played_cycles+=committed.speed*dt
        for item in self.items:
            old=item.phase;item.phase+=item.direction*item.speed*dt if item.mode!='low_swing' else item.speed*dt
            item.visual=False;item.turn_supported=False;item.upper_supported=False;item.exit_supported=False
            # Unconfirmed state hypotheses may play, but cannot spawn another
            # skill or reverse the confirmed direction behind the active model.
            if committed is not None and item.mode!=committed.mode:continue
            # Branch only at a legal path boundary; retain the unchanged parent.
            boundary=self.ground_boundary(item)
            if dt<=.15 and self.crossed(old,item.phase,boundary):
                for gear in range(len(self.gears(item.mode))):
                    if item.key==self.active and gear!=item.gear:
                        child=self.make(item.mode,item.phase,gear,item.origin,item.score-.015,item.key)
                        # Apply the new speed to the time remaining AFTER the crossing.
                        target=(math.floor(old-boundary)+1)+boundary if item.direction>0 or item.mode=='low_swing' else math.floor(old-boundary)+boundary
                        crossing_dt=abs(target-old)/item.speed
                        child.phase=target+(1 if item.mode=='low_swing' else item.direction)*child.speed*max(0.,dt-crossing_dt)
                        branches.append(child)
                if item.mode!='low_swing' and item.key==self.active and self.rotation_rearmed:
                    # Experimental direction-specific entry pose; this differs
                    # from the baseline and has not passed replay checks.
                    for phase in [self.low_starts[item.direction]]:
                        for gear in range(len(self.gears('low_swing'))):
                            hint=self.rate_hint if self.rate_hint_mode==item.mode and self.rate_hint and now-self.rate_hint['time']<=.3 else None
                            expected=(hint['rate'] if hint else item.speed)*self.c.get('swing_rotation_rate_ratio',.54656)
                            prior=self.c.get('rate_prior_weight',0)*min(1.,abs(self.gears('low_swing')[gear]-expected)/.12)
                            child=self.make('low_swing',phase,gear,item.direction,item.score-.025-prior,item.key)
                            target=(math.floor(old-boundary)+1)+boundary if item.direction>0 else math.floor(old-boundary)+boundary
                            child.phase+=child.speed*max(0.,dt-abs(target-old)/item.speed)
                            branches.append(child)
                elif item.mode=='low_swing' and item.key==self.active and self.low_phase_travel>=self.c.get('minimum_swing_cycles',2.):
                    entry=self.low_entry_direction if self.low_entry_direction is not None else item.origin
                    mode='rotation_reverse' if entry>0 else 'rotation_forward'
                    for gear in range(len(self.gears(mode))):
                        child=self.make(mode,self.normal_pose[-entry],gear,-entry,item.score-.025,item.key)
                        child.phase+=child.direction*child.speed*max(0.,dt-((math.floor(old-boundary)+1)+boundary-old)/item.speed)
                        branches.append(child)
        self.items.extend(branches)
        window=self.c.get('transition_evidence_window',.75)
        self.items=[p for p in self.items if p.key==self.active or p.epoch==self.epoch and (committed is None or p.mode==committed.mode or now-p.born<=window)]
        self.prune()
        return dt

