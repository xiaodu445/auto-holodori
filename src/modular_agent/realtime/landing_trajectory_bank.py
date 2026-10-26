"""Landing-anchored branch playback. Baseline TrajectoryBank remains available.

A fresh branch may catch up by its played trajectory only after common-window
visual evidence; this is distinct from unconstrained per-frame phase correction.
"""
from collections import deque
import math
from modular_agent.realtime.trajectory_bank import TrajectoryBank


class LandingTrajectoryBank(TrajectoryBank):
    def __init__(self,settings,boundary,swing_entry):
        for name,default,lo,hi in [('branch_lifetime',.9,.3,1.5),('branch_evidence_window',.22,.08,.5),('branch_evidence_span',.045,.02,.2),('branch_evidence_margin',.025,0.,.2),('branch_quality_min',.45,.4,.9),('branch_motion_min',.03,.01,.5)]:
            value=settings.get(name,default)
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('invalid '+name)
        if type(settings.get("branch_actual_support",False)) is not bool:raise ValueError("invalid branch_actual_support")
        frames=settings.get('branch_evidence_frames',4)
        if type(frames) is not int or not 3<=frames<=12:raise ValueError('invalid branch_evidence_frames')
        if settings.get("branch_scope","all") not in ("all","rotation_speed"):raise ValueError("invalid branch_scope")
        if type(settings.get('expire_legacy_hypotheses',False)) is not bool:raise ValueError('invalid expire_legacy_hypotheses')
        if not 0<settings.get('branch_max_clock_gap',.5)<=.5:raise ValueError('invalid branch_max_clock_gap')
        if type(settings.get('window_branch_confirmation',False)) is not bool:raise ValueError('invalid window_branch_confirmation')
        if type(settings.get('exit_window_confirmation',False)) is not bool:raise ValueError('invalid exit_window_confirmation')
        if type(settings.get('exit_speed_branches',False)) is not bool:raise ValueError('invalid exit_speed_branches')
        self.spawning=False
        super().__init__(dict(settings,transition_evidence_window=settings.get('branch_lifetime',.9)),boundary,swing_entry)

    def reset(self):
        super().reset();self.landing_number=0;self.resolved_landing=0;self.branch_info={};self.evidence={};self.last_branch_adoption=None;self.branch_adoptions=0;self.spawning=False

    def make(self,*args,**kwargs):
        item=super().make(*args,**kwargs)
        active=next((p for p in self.items if p.key==self.active),None)
        in_scope=self.c.get("branch_scope","all")=="all" or active is not None and item.mode==active.mode and item.mode!="low_swing"
        if self.spawning and item.parent is not None and in_scope:
            self.branch_info[item.key]=dict(landing=self.landing_number,time=self.time,epoch=self.epoch)
        return item

    def advance(self,now):
        active=next((p for p in self.items if p.key==self.active),None)
        dt=0. if self.time is None else now-self.time
        crossing=False
        if active is not None and 0<dt<=.15:
            boundary=self.swing_boundary(active) if active.mode=='low_swing' else self.boundary
            next_phase=active.phase+(active.direction if active.mode!='low_swing' else 1)*active.speed*dt
            crossing=self.crossed(active.phase,next_phase,boundary)
        if crossing:self.landing_number+=1
        self.spawning=crossing
        try:
            elapsed=super().advance(now)
            if crossing and (self.c.get("branch_scope","all")=="all" or active.mode!="low_swing"):
                # Include unchanged nominal gear as a fresh branch, rather than
                # comparing a newborn alternative only to an old corrected clock.
                fresh=self.make(active.mode,active.phase,active.gear,active.origin,active.score-.015,active.key)
                boundary=self.swing_boundary(active) if active.mode=='low_swing' else self.boundary
                old=active.phase-(active.direction if active.mode!='low_swing' else 1)*active.speed*dt
                target=math.floor(old-boundary)+1+boundary if active.mode=='low_swing' or active.direction>0 else math.floor(old-boundary)+boundary
                fresh.phase=target+(1 if active.mode=='low_swing' else active.direction)*fresh.speed*max(0.,dt-abs(target-old)/active.speed)
                self.items.append(fresh)
        finally:self.spawning=False
        self.prune()
        return elapsed

    def prune(self):
        active=next((p for p in self.items if p.key==self.active),None)
        groups={};lifetime=self.c.get('branch_lifetime',.9)
        for p in self.items:
            info=self.branch_info.get(p.key)
            if self.c.get('expire_legacy_hypotheses',False) and p.key!=self.active and info is None and self.time-p.born>lifetime:continue
            if p.key!=self.active and info and (self.time-info['time']>lifetime or info['landing']<=self.resolved_landing):continue
            branch=1 if p.coordinate_velocity>=0 else -1
            key=(info['landing'] if info else -1,p.mode,p.gear,p.origin if p.mode=='low_swing' else 0,branch if p.mode=='low_swing' else 0)
            if key not in groups or p.score>groups[key].score:groups[key]=p
        # Fresh boundary cohorts cannot be eliminated by a high historical score.
        ordered=sorted(groups.values(),key=lambda p:(self.branch_info.get(p.key,{}).get('landing',-1),p.score),reverse=True)
        self.items=ordered[:self.c['max_hypotheses']]
        if active and all(p.key!=active.key for p in self.items):self.items=self.items[:self.c['max_hypotheses']-1]+[active]
        keys={p.key for p in self.items}
        self.branch_info={k:v for k,v in self.branch_info.items() if k in keys}
        self.evidence={k:v for k,v in self.evidence.items() if k in keys}

    def commit_episode(self,active,best):
        exiting=active.mode=='low_swing' and best.mode!='low_swing'
        super().commit_episode(active,best)
        if exiting and self.c.get('exit_speed_branches',False):
            # Direction confirmation does not resolve speed. The surviving
            # exit cohort shares the same boundary and must still compete.
            self.landing_number+=1
            self.branch_info={p.key:dict(landing=self.landing_number,time=self.time,epoch=self.epoch,exit_cohort=True) for p in self.items}
            self.evidence={}

    def correct(self,item,error,dt,quality,moving):
        active=next((p for p in self.items if p.key==self.active),None)
        if self.c.get('exit_speed_branches',False) and active is not None and active.mode=='low_swing' and item.mode!='low_swing' and item.parent is not None:return
        if item.key in self.branch_info and item.key!=self.active:return
        super().correct(item,error,dt,quality,moving)
        hint=self.rate_hint
        if self.c.get('rotation_rate_assist',False) and item.key==self.active and item.mode!='low_swing' and hint is not None and self.rate_hint_mode==item.mode and self.time-hint['time']<=.12 and item.visual and quality>=.4 and moving>=.03:
            lo,hi=self.bounds(item);item.speed=max(lo,min(hi,.8*hint['rate']+.2*item.speed))

    def recover_rotation(self,coordinate,now):
        active=next((p for p in self.items if p.key==self.active),None)
        if active is None or active.mode=='low_swing':return False
        if any(info.get('observed_clock',False) and now-info['time']<self.c.get('branch_lifetime',.9) for info in self.branch_info.values()):return False
        phase=self.rotation_clock(active.mode,coordinate)
        phase+=round(active.phase-phase)
        self.landing_number+=1
        self.items=[active];self.branch_info={};self.evidence={};self.pending=None;self.pending_since=None
        for gear in range(len(self.gears(active.mode))):
            clock=self.rotation_clock(active.mode,coordinate,gear);clock+=round(active.phase-clock)
            child=self.make(active.mode,clock,gear,active.direction,parent=active.key)
            self.items.append(child)
            self.branch_info[child.key]=dict(landing=self.landing_number,time=now,epoch=self.epoch,observed_clock=True)
        return True

    def record_evidence(self,item,target,quality,moving):
        records=self.evidence.setdefault(item.key,deque())
        records.append((self.time,float(target),bool(item.visual and quality>=self.c.get('branch_quality_min',.45) and moving>=self.c.get('branch_motion_min',.03) and (not self.c.get('branch_actual_support',False) or item.turn_supported))))
        while records and self.time-records[0][0]>self.c.get('branch_evidence_window',.22):records.popleft()

    def branch_advantage(self,active,item):
        reference={t:score for t,score,_ in self.evidence.get(active.key,())}
        paired=[score-reference[t] for t,score,_ in self.evidence.get(item.key,()) if t in reference]
        return sum(paired)/len(paired) if paired else None

    def supported_branch(self,active,item,now):
        info=self.branch_info.get(item.key)
        if not info or info['landing']<=self.resolved_landing or info['epoch']!=self.epoch or now-info['time']>self.c.get('branch_lifetime',.9):return False
        if abs((item.phase-active.phase+.5)%1-.5)>self.c.get('branch_max_clock_gap',.5):return False
        candidates=self.evidence.get(item.key,());reference={t:score for t,score,_ in self.evidence.get(active.key,())}
        paired=[(t,score-reference[t],good) for t,score,good in candidates if t in reference]
        good=[r for r in paired if r[2]]
        if len(good)<self.c.get('branch_evidence_frames',4) or good[-1][0]!=now or good[-1][0]-good[0][0]<self.c.get('branch_evidence_span',.045):return False
        # Compare identical frame times, including missed candidate evidence.
        return sum(r[1] for r in paired)/len(paired)>self.c.get('branch_evidence_margin',.025)

    def legal_successor(self,active,item,now):
        if not super().legal_successor(active,item,now):return False
        if item.key in self.branch_info:return self.supported_branch(active,item,now)
        # Legacy acquisition models cannot bypass landing sequence confirmation.
        if item.mode==active.mode and (any(k!=self.active for k in self.branch_info) or active.mode!='low_swing' and self.landing_number>0):return False
        return True

    def phase_compatible(self,active,item,now):
        return item.key in self.branch_info or super().phase_compatible(active,item,now)

    def choose(self,now,dt,compatible=None):
        prior=next((p for p in self.items if p.key==self.active),None)
        phases={p.key:p.phase for p in self.items};infos=dict(self.branch_info)
        candidates=[]
        if self.c.get('window_branch_confirmation',False) and prior is not None and prior.mode!='low_swing' and prior.mode in self.c.get('window_branch_modes',['rotation_forward','rotation_reverse']):
            for p in self.items:
                if p.key==prior.key or p.mode!=prior.mode or not self.legal_successor(prior,p,now):continue
                if compatible is not None and not compatible(prior,p):continue
                good=[r for r in self.evidence.get(p.key,()) if r[2]]
                if len(good)>=5 and good[-1][0]-good[0][0]>=max(.10,self.c['confirmation_seconds']):candidates.append(p)
        if self.c.get('exit_window_confirmation',False) and prior is not None:
            for p in self.items:
                is_exit=prior.mode=='low_swing' and p.mode!='low_swing'
                is_exit_speed=prior.mode!='low_swing' and p.mode==prior.mode and not self.rotation_rearmed and self.branch_info.get(p.key,{}).get('exit_cohort',False)
                if not (is_exit or is_exit_speed) or p.key==prior.key or not p.visual or not self.legal_successor(prior,p,now):continue
                if compatible is not None and not compatible(prior,p):continue
                good=[r for r in self.evidence.get(p.key,()) if r[2]]
                advantage=self.branch_advantage(prior,p)
                if len(good)>=5 and good[-1][0]-good[0][0]>=.12 and good[-1][0]==now and advantage is not None and advantage>.08:candidates.append(p)
        if candidates:
            selected=max(candidates,key=lambda p:self.branch_advantage(prior,p))
            if selected.mode!=prior.mode:
                self.mode_switches+=1;self.commit_episode(prior,selected)
            self.active=selected.key;self.switches+=1;self.gear_switches+=int(selected.gear!=prior.gear and selected.mode==prior.mode)
            self.pending=None;self.pending_since=None;self.weak_seconds=0. if selected.visual else self.weak_seconds+dt
        else:selected=super().choose(now,dt,compatible)
        if prior is not None and selected is not None and selected.key!=prior.key and selected.key in infos:
            # The hypothesis has already integrated time since the landing.
            # Do not move it back to the stale active clock on confirmed adoption.
            if selected.mode==prior.mode:
                selected.phase=phases[selected.key]
            self.resolved_landing=infos[selected.key]['landing']
            self.branch_adoptions+=1
            self.last_branch_adoption=dict(time=now,landing=infos[selected.key]['landing'],from_mode=prior.mode,to_mode=selected.mode,gear=selected.gear,phase_difference=(selected.phase-prior.phase+.5)%1-.5)
            self.event='confirmed_landing_branch'
            self.prune()
        return selected
