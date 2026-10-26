"""Bounded-rate trajectory playback and competing boundary transitions. No CV/input."""
from dataclasses import dataclass
import math


class AngularWarp:
    """Monotone periodic cubic clock-to-motion map with analytic derivatives."""
    def __init__(self,data=None):
        import numpy as np
        self.np=np
        self.x=np.array((data or {}).get('clock_nodes',[0.,1.]),dtype=float)
        self.y=np.array((data or {}).get('angle_nodes',[0.,1.]),dtype=float)
        if len(self.x)!=len(self.y) or len(self.x)<2 or not np.all(np.isfinite(self.x)) or not np.all(np.isfinite(self.y)) or self.x[0]!=0 or self.x[-1]!=1 or self.y[0]!=0 or self.y[-1]!=1 or np.any(np.diff(self.x)<=0) or np.any(np.diff(self.y)<=0):raise ValueError('invalid monotone swing time profile')
        h=np.diff(self.x);sec=np.diff(self.y)/h
        slope=np.empty(len(self.x));slope[0]=slope[-1]=2/(1/sec[0]+1/sec[-1])
        for i in range(1,len(self.x)-1):
            w1=2*h[i]+h[i-1];w2=h[i]+2*h[i-1]
            slope[i]=(w1+w2)/(w1/sec[i-1]+w2/sec[i])
        self.slopes=slope
        if min(self.evaluate(t)[1] for t in np.linspace(0,1,2001))<=0:raise ValueError('swing profile stops or reverses clock motion')

    def evaluate(self,phase):
        np=self.np;x=float(phase)%1;i=min(int(np.searchsorted(self.x,x,side='right')-1),len(self.x)-2)
        h=self.x[i+1]-self.x[i];u=(x-self.x[i])/h;y0,y1=self.y[i:i+2];m0,m1=self.slopes[i:i+2]
        value=(2*u**3-3*u*u+1)*y0+(u**3-2*u*u+u)*h*m0+(-2*u**3+3*u*u)*y1+(u**3-u*u)*h*m1
        first=((6*u*u-6*u)*y0+(-6*u*u+6*u)*y1)/h+(3*u*u-4*u+1)*m0+(3*u*u-2*u)*m1
        second=((12*u-6)*y0+(-12*u+6)*y1)/h**2+(6*u-4)*m0/h+(6*u-2)*m1/h
        return float(value),float(first),float(second)

    def inverse(self,angle):
        target=float(angle)%1;lo=0.;hi=1.
        for _ in range(42):
            mid=(lo+hi)/2
            if self.evaluate(mid)[0]<target:lo=mid
            else:hi=mid
        return (lo+hi)/2


@dataclass
class Playback:
    key: int
    mode: str
    phase: float
    speed: float
    gear: int
    origin: int = 1
    score: float = 0.
    parent: int | None = None
    visual: bool = False
    epoch: int = 0
    born: float = 0.
    turn_supported: bool = False
    warp: AngularWarp | None = None
    upper_supported: bool = False
    exit_supported: bool = False
    recovered_exit: bool = False
    estimated_boundary_time: float | None = None

    @property
    def direction(self):
        return -1 if self.mode == 'rotation_reverse' else 1

    @property
    def angle(self):
        return self.warp.evaluate(self.phase)[0] if self.warp else self.phase%1

    @property
    def coordinate(self):
        return (1-math.cos(2*math.pi*self.angle))/2 if self.mode == 'low_swing' else self.phase%1


    @property
    def coordinate_velocity(self):
        return math.pi*self.speed*math.sin(2*math.pi*self.angle)*(self.warp.evaluate(self.phase)[1] if self.warp else 1.) if self.mode=='low_swing' else self.direction*self.speed

    @property
    def template_acceleration(self):
        # Instantaneous coordinate acceleration of constant-rate playback. At
        # both swing turns velocity is zero but this acceleration is nonzero.
        if self.mode!='low_swing':return 0.
        angle,first,second=self.warp.evaluate(self.phase) if self.warp else (self.angle,1.,0.)
        return 2*math.pi**2*self.speed**2*math.cos(2*math.pi*angle)*first**2+math.pi*self.speed**2*math.sin(2*math.pi*angle)*second


class TrajectoryBank:
    def __init__(self, settings, boundary, swing_entry):
        self.c=settings;self.boundary=float(boundary)%1
        self.warp=AngularWarp(settings.get("swing_time_profile"))
        self.swing_entry=self.warp.inverse(swing_entry)
        self.swing_entries=(self.swing_entry,self.warp.inverse(-swing_entry))
        for name in ('rotation_gears','swing_gears'):
            values=settings[name]
            if not values or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in values) or any(a>=b for a,b in zip(values,values[1:])):
                raise ValueError('invalid positive ordered '+name)
        for name in ('gear_tolerance','phase_correction_fraction','max_phase_correction','switch_margin','confirmation_seconds'):
            if type(settings[name]) not in (int,float) or not math.isfinite(settings[name]) or settings[name]<=0:raise ValueError('invalid '+name)
        if settings['gear_tolerance']>=.5 or settings['phase_correction_fraction']>=.5 or settings['max_phase_correction']>.03:raise ValueError('unsafe playback correction bounds')
        for name,default in [('swing_gear_tolerance',settings['gear_tolerance']),('transition_evidence_window',.75)]:
            value=settings.get(name,default)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<(0.5 if name=='swing_gear_tolerance' else 2.):raise ValueError('invalid '+name)
        if type(settings.get('occlusion_tolerant_rearm',False)) is not bool:raise ValueError('invalid occlusion_tolerant_rearm')
        if type(settings.get('freeze_unconfirmed_correction',False)) is not bool:raise ValueError('invalid freeze_unconfirmed_correction')
        for name,default in [('rate_adaptation_gain',.08),('rate_step_limit',.015)]:
            value=settings.get(name,default)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=.1:raise ValueError('invalid '+name)
        if type(settings['max_hypotheses']) is not int or not 4<=settings['max_hypotheses']<=64:raise ValueError('invalid bank size')
        self.reset()

    def reset(self):
        self.time=None;self.items=[];self.active=None;self.serial=0;self.pending=None;self.pending_since=None
        self.last_exit_recovered=False;self.estimated_transition_time=None;self.low_played_cycles=0.;self.epoch=0;self.low_episode=0;self.low_entry_direction=None;self.low_turns=set();self.rotation_rearmed=True;self.rearm_travel=0.;self.rearm_phase=None;self.rearm_supported=False;self.rearm_played_cycles=0.;self.rearm_upper_travel=0.;self.rearm_upper_phase=None;self.rearm_upper_supported=False
        self.rate_hint=None;self.rate_hint_mode=None;self.entering_rate_hint=None
        self.switches=0;self.mode_switches=0;self.gear_switches=0;self.direction_changes=0;self.event=None;self.locked=False;self.weak_seconds=0.

    def gears(self,mode):return self.c['swing_gears' if mode=='low_swing' else 'rotation_gears']

    def bounds(self,item):
        center=self.gears(item.mode)[item.gear];r=self.c.get('swing_gear_tolerance',self.c['gear_tolerance']) if item.mode=='low_swing' else self.c['gear_tolerance']
        return center*(1-r),center*(1+r)

    def make(self,mode,phase,gear,origin=1,score=0.,parent=None):
        self.serial+=1
        return Playback(self.serial,mode,float(phase),self.gears(mode)[gear],gear,origin,score,parent,epoch=self.epoch,born=self.time or 0.,warp=self.warp if mode=='low_swing' else None)

    def acquire(self,phase,now,direction=1):
        if not math.isfinite(phase) or not math.isfinite(now):raise ValueError('invalid acquisition')
        mode='rotation_forward' if direction>0 else 'rotation_reverse'
        self.items=[self.make(mode,phase,i,direction) for i in range(len(self.gears(mode)))]
        self.active=min(self.items,key=lambda p:abs(p.speed-self.c.get('initial_rotation_rate',self.gears(mode)[0]))).key;self.time=now;self.locked=True
        self.event='acquired_rotation';self.weak_seconds=0.

    @staticmethod
    def crossed(a,b,target):
        return math.floor(a-target)!=math.floor(b-target)

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
            boundary=self.swing_entry if item.mode=='low_swing' else self.boundary
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
                    # Both finite-path directions are legal initial hypotheses;
                    # subsequent frames select the supported one.
                    for phase in self.swing_entries:
                        for gear in range(len(self.gears('low_swing'))):
                            hint=self.rate_hint if self.rate_hint_mode==item.mode and self.rate_hint and now-self.rate_hint['time']<=.3 else None
                            expected=(hint['rate'] if hint else item.speed)*self.c.get('swing_rotation_rate_ratio',.54656)
                            prior=self.c.get('rate_prior_weight',0)*min(1.,abs(self.gears('low_swing')[gear]-expected)/.12)
                            child=self.make('low_swing',phase,gear,item.direction,item.score-.025-prior,item.key)
                            target=(math.floor(old-self.boundary)+1)+self.boundary if item.direction>0 else math.floor(old-self.boundary)+self.boundary
                            child.phase+=child.speed*max(0.,dt-abs(target-old)/item.speed)
                            branches.append(child)
                elif item.mode=='low_swing' and item.key==self.active and (self.low_turns=={-1,1} or self.low_played_cycles>=1.):
                    entry=self.low_entry_direction if self.low_entry_direction is not None else item.origin
                    mode='rotation_reverse' if entry>0 else 'rotation_forward'
                    for gear in range(len(self.gears(mode))):
                        child=self.make(mode,self.boundary,gear,-entry,item.score-.025,item.key)
                        child.phase+=child.direction*child.speed*max(0.,dt-((math.floor(old-self.swing_entry)+1)+self.swing_entry-old)/item.speed)
                        branches.append(child)
        self.items.extend(branches)
        window=self.c.get('transition_evidence_window',.75)
        self.items=[p for p in self.items if p.key==self.active or p.epoch==self.epoch and (committed is None or p.mode==committed.mode or now-p.born<=window)]
        self.prune()
        return dt

    def correct(self,item,error,dt,quality,moving):
        """Small clock correction cannot cancel travel or change mode/direction."""
        if self.c.get('freeze_unconfirmed_correction',False) and item.key!=self.active:return
        if not item.visual or dt<=0 or quality<.4 or moving<.03:return
        travel=item.speed*dt
        limit=min(self.c['max_phase_correction'],travel*self.c['phase_correction_fraction'])
        item.phase+=max(-limit,min(limit,error*.25))
        lo,hi=self.bounds(item)
        signed_error=error*item.direction if item.mode!='low_swing' else error
        item.speed=max(lo,min(hi,item.speed+max(-self.c.get('rate_step_limit',.015),min(self.c.get('rate_step_limit',.015),signed_error*self.c.get('rate_adaptation_gain',.08)/dt))))

    def prune(self):
        groups={}
        active=next((p for p in self.items if p.key==self.active),None)
        for p in self.items:
            # Keep alternative swing directions and each speed/mode, not just
            # copies of the currently most attractive image branch.
            branch=1 if p.coordinate_velocity>=0 else -1
            key=(p.mode,p.gear,p.origin if p.mode=='low_swing' else 0,branch if p.mode=='low_swing' else 0)
            if key not in groups or p.score>groups[key].score:groups[key]=p
        self.items=sorted(groups.values(),key=lambda p:p.score,reverse=True)[:self.c['max_hypotheses']]
        if active and all(p.key!=active.key for p in self.items):
            self.items=self.items[:self.c['max_hypotheses']-1]+[active]

    def reconstruct_exit(self,phase,rate,now):
        """Called only after independent upper-arc image-chain confirmation.

        Recover a missed ground transition, not a new skill. Direction remains
        the opposite of this episode's frozen entry direction.
        """
        active=next((p for p in self.items if p.key==self.active),None)
        if active is None or active.mode!='low_swing' or self.low_played_cycles<1. or self.low_entry_direction is None:return None
        if not math.isfinite(phase) or not math.isfinite(rate) or rate<=0:return None
        expected=-self.low_entry_direction;mode='rotation_forward' if expected>0 else 'rotation_reverse'
        gear=min(range(len(self.gears(mode))),key=lambda i:abs(self.gears(mode)[i]-rate))
        candidate=self.make(mode,phase,gear,expected,parent=active.key)
        lo,hi=self.bounds(candidate)
        if not lo<=rate<=hi:return None
        candidate.speed=rate;candidate.exit_supported=True;candidate.recovered_exit=True
        distance=(phase-self.boundary)%1 if expected>0 else (self.boundary-phase)%1
        candidate.estimated_boundary_time=now-distance/rate
        self.items.append(candidate)
        return candidate

    def legal_successor(self,active,p,now):
        if p.epoch!=self.epoch:return False
        if p.mode==active.mode:
            return p.mode!='low_swing' or p.origin==self.low_entry_direction
        if p.parent is None or now-p.born>self.c.get('transition_evidence_window',.75):return False
        if active.mode=='low_swing':
            expected='rotation_reverse' if self.low_entry_direction==1 else 'rotation_forward'
            return p.mode==expected and (self.low_turns=={-1,1} or self.low_played_cycles>=1. and p.exit_supported)
        return p.mode=='low_swing' and self.rotation_rearmed and p.origin==active.direction

    def commit_episode(self,active,best):
        self.epoch+=1
        if best.mode=='low_swing':
            self.entering_rate_hint=self.rate_hint if self.rate_hint_mode==active.mode else None
            self.rate_hint=None;self.rate_hint_mode=None
            self.low_episode+=1;self.low_entry_direction=active.direction;self.low_turns=set();self.low_played_cycles=0.
            best.origin=self.low_entry_direction
        else:
            self.rate_hint=None;self.rate_hint_mode=None
            self.last_exit_recovered=best.recovered_exit;self.estimated_transition_time=best.estimated_boundary_time
            self.direction_changes+=1;self.rotation_rearmed=False
            self.rearm_travel=0.;self.rearm_phase=None;self.rearm_supported=False
            self.rearm_played_cycles=0.;self.rearm_upper_travel=0.;self.rearm_upper_phase=None;self.rearm_upper_supported=False
        # Forget every stale/opposite branch after a confirmed state transition.
        cohort=[p for p in self.items if p.mode==best.mode and p.origin==best.origin and abs(p.born-best.born)<.10]
        if best not in cohort:cohort.append(best)
        self.items=cohort
        for p in self.items:p.epoch=self.epoch

    def choose(self,now,dt,compatible=None):
        if not self.items:return None
        active=next(p for p in self.items if p.key==self.active)
        if active.mode=='low_swing':
            if self.low_entry_direction is None:self.low_entry_direction=active.origin
            if active.turn_supported:
                if active.coordinate>=.90:self.low_turns.add(1)
                if active.coordinate<=.10:self.low_turns.add(-1)
        elif not self.rotation_rearmed:
            if active.turn_supported and self.rearm_supported and self.rearm_phase is not None and dt<=.1:
                self.rearm_travel+=abs(active.phase-self.rearm_phase)
            self.rearm_phase=active.phase;self.rearm_supported=active.turn_supported
            if active.upper_supported and self.rearm_upper_supported and self.rearm_upper_phase is not None and dt<=.1:
                self.rearm_upper_travel+=abs(active.phase-self.rearm_upper_phase)
            self.rearm_upper_phase=active.phase;self.rearm_upper_supported=active.upper_supported
            protected_rearm=self.c.get('occlusion_tolerant_rearm',False) and self.rearm_played_cycles>=1. and self.rearm_upper_travel>=.08
            if self.rearm_travel>=1. or protected_rearm:self.rotation_rearmed=True
        eligible=[p for p in self.items if p.key==active.key or
            (self.legal_successor(active,p,now) and (p.mode!=active.mode or abs((p.phase-active.phase+.5)%1-.5)<=self.c['max_phase_correction'] or
             p.parent is not None and p.gear!=active.gear and now-p.born<=self.c.get('transition_evidence_window',.75)) and
             (compatible is None or compatible(active,p)))]
        best=max(eligible,key=lambda p:p.score)
        if best.visual and best.key!=active.key and best.score>active.score+self.c['switch_margin']:
            # Compare model identity rather than transient object ids at branching.
            signature=(best.mode,best.gear,best.origin,(1 if best.coordinate_velocity>=0 else -1) if best.mode=='low_swing' else 0)
            if signature!=self.pending:self.pending=signature;self.pending_since=now
            elif now-self.pending_since>=(max(self.c['confirmation_seconds'],.20) if active.mode=='low_swing' and best.mode!=active.mode and self.low_turns!={-1,1} else self.c['confirmation_seconds']):
                self.mode_switches+=int(best.mode!=active.mode)
                self.gear_switches+=int(best.gear!=active.gear and best.mode==active.mode)
                if best.mode!=active.mode:self.commit_episode(active,best)
                if best.mode==active.mode:
                    best.phase+=round(active.phase-best.phase)
                    gap=best.phase-active.phase;limit=min(self.c['max_phase_correction'],active.speed*dt*self.c['phase_correction_fraction'])
                    best.phase=active.phase+max(-limit,min(limit,gap))
                self.active=best.key;active=best;self.switches+=1;self.event='confirmed_boundary_branch'
                self.pending=None;self.pending_since=None
        else:self.pending=None;self.pending_since=None
        self.weak_seconds=0. if active.visual else self.weak_seconds+dt
        self.prune()
        return active
