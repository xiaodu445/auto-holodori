"""Bounded-rate trajectory playback and competing boundary transitions. No CV/input."""
from dataclasses import dataclass, replace
import math


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

    @property
    def direction(self):
        return -1 if self.mode == 'rotation_reverse' else 1

    @property
    def coordinate(self):
        return (1-math.cos(2*math.pi*self.phase))/2 if self.mode == 'low_swing' else self.phase%1


    @property
    def coordinate_velocity(self):
        return math.pi*self.speed*math.sin(2*math.pi*self.phase) if self.mode=='low_swing' else self.direction*self.speed

    @property
    def template_acceleration(self):
        # Instantaneous coordinate acceleration of constant-rate playback. At
        # both swing turns velocity is zero but this acceleration is nonzero.
        return 2*math.pi**2*self.speed**2*math.cos(2*math.pi*self.phase) if self.mode=='low_swing' else 0.


class TrajectoryBank:
    def __init__(self, settings, boundary, swing_entry):
        self.c=settings;self.boundary=float(boundary)%1;self.swing_entry=float(swing_entry)%1
        for name in ('rotation_gears','swing_gears'):
            values=settings[name]
            if not values or any(type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in values) or any(a>=b for a,b in zip(values,values[1:])):
                raise ValueError('invalid positive ordered '+name)
        for name in ('gear_tolerance','phase_correction_fraction','max_phase_correction','switch_margin','confirmation_seconds'):
            if type(settings[name]) not in (int,float) or not math.isfinite(settings[name]) or settings[name]<=0:raise ValueError('invalid '+name)
        if settings['gear_tolerance']>=.5 or settings['phase_correction_fraction']>=.5 or settings['max_phase_correction']>.03:raise ValueError('unsafe playback correction bounds')
        if type(settings['max_hypotheses']) is not int or not 4<=settings['max_hypotheses']<=64:raise ValueError('invalid bank size')
        self.reset()

    def reset(self):
        self.time=None;self.items=[];self.active=None;self.serial=0;self.pending=None;self.pending_since=None
        self.switches=0;self.mode_switches=0;self.gear_switches=0;self.direction_changes=0;self.event=None;self.locked=False;self.weak_seconds=0.

    def gears(self,mode):return self.c['swing_gears' if mode=='low_swing' else 'rotation_gears']

    def bounds(self,item):
        center=self.gears(item.mode)[item.gear];r=self.c['gear_tolerance']
        return center*(1-r),center*(1+r)

    def make(self,mode,phase,gear,origin=1,score=0.,parent=None):
        self.serial+=1
        return Playback(self.serial,mode,float(phase),self.gears(mode)[gear],gear,origin,score,parent)

    def acquire(self,phase,now,direction=1):
        if not math.isfinite(phase) or not math.isfinite(now):raise ValueError('invalid acquisition')
        mode='rotation_forward' if direction>0 else 'rotation_reverse'
        self.items=[self.make(mode,phase,i,direction) for i in range(len(self.gears(mode)))]
        self.active=self.items[len(self.items)//2].key;self.time=now;self.locked=True
        self.event='acquired_rotation';self.weak_seconds=0.

    @staticmethod
    def crossed(a,b,target):
        return math.floor(a-target)!=math.floor(b-target)

    def advance(self,now):
        if not math.isfinite(now) or self.time is not None and now<=self.time:raise ValueError('nonmonotonic playback clock')
        dt=0. if self.time is None else now-self.time;self.time=now;self.event=None
        branches=[]
        for item in self.items:
            old=item.phase;item.phase+=item.direction*item.speed*dt if item.mode!='low_swing' else item.speed*dt
            item.visual=False
            # Branch only at a legal path boundary; retain the unchanged parent.
            boundary=self.swing_entry if item.mode=='low_swing' else self.boundary
            if dt<=.15 and self.crossed(old,item.phase,boundary):
                for gear in (item.gear-1,item.gear+1):
                    if 0<=gear<len(self.gears(item.mode)):
                        child=self.make(item.mode,item.phase,gear,item.origin,item.score-.015,item.key)
                        # Apply the new speed to the time remaining AFTER the crossing.
                        target=(math.floor(old-boundary)+1)+boundary if item.direction>0 or item.mode=='low_swing' else math.floor(old-boundary)+boundary
                        crossing_dt=abs(target-old)/item.speed
                        child.phase=target+(1 if item.mode=='low_swing' else item.direction)*child.speed*max(0.,dt-crossing_dt)
                        branches.append(child)
                if item.mode!='low_swing':
                    # Both finite-path directions are legal initial hypotheses;
                    # subsequent frames select the supported one.
                    for phase in (self.swing_entry,(-self.swing_entry)%1):
                        for gear in range(len(self.gears('low_swing'))):
                            child=self.make('low_swing',phase,gear,item.direction,item.score-.025,item.key)
                            target=(math.floor(old-self.boundary)+1)+self.boundary if item.direction>0 else math.floor(old-self.boundary)+self.boundary
                            child.phase+=child.speed*max(0.,dt-abs(target-old)/item.speed)
                            branches.append(child)
                else:
                    mode='rotation_reverse' if item.origin>0 else 'rotation_forward'
                    for gear in range(len(self.gears(mode))):
                        child=self.make(mode,self.boundary,gear,-item.origin,item.score-.025,item.key)
                        child.phase+=child.direction*child.speed*max(0.,dt-((math.floor(old-self.swing_entry)+1)+self.swing_entry-old)/item.speed)
                        branches.append(child)
        self.items.extend(branches)
        self.prune()
        return dt

    def correct(self,item,error,dt,quality,moving):
        """Small clock correction cannot cancel travel or change mode/direction."""
        if not item.visual or dt<=0 or quality<.4 or moving<.03:return
        travel=item.speed*dt
        limit=min(self.c['max_phase_correction'],travel*self.c['phase_correction_fraction'])
        item.phase+=max(-limit,min(limit,error*.25))
        lo,hi=self.bounds(item)
        signed_error=error*item.direction if item.mode!='low_swing' else error
        item.speed=max(lo,min(hi,item.speed+max(-.015,min(.015,signed_error*.08/dt))))

    def prune(self):
        groups={}
        active=next((p for p in self.items if p.key==self.active),None)
        for p in self.items:
            # Keep alternative swing directions and each speed/mode, not just
            # copies of the currently most attractive image branch.
            branch=1 if math.sin(2*math.pi*p.phase)>=0 else -1
            key=(p.mode,p.gear,p.origin if p.mode=='low_swing' else 0,branch if p.mode=='low_swing' else 0)
            if key not in groups or p.score>groups[key].score:groups[key]=p
        self.items=sorted(groups.values(),key=lambda p:p.score,reverse=True)[:self.c['max_hypotheses']]
        if active and all(p.key!=active.key for p in self.items):
            self.items=self.items[:self.c['max_hypotheses']-1]+[active]

    def choose(self,now,dt,compatible=None):
        if not self.items:return None
        active=next(p for p in self.items if p.key==self.active)
        eligible=[p for p in self.items if p.key==active.key or
            ((p.mode!=active.mode or abs((p.phase-active.phase+.5)%1-.5)<=self.c['max_phase_correction']) and
             (compatible is None or compatible(active,p)))]
        best=max(eligible,key=lambda p:p.score)
        if best.visual and best.key!=active.key and best.score>active.score+self.c['switch_margin']:
            # Compare model identity rather than transient object ids at branching.
            signature=(best.mode,best.gear,best.origin,(1 if math.sin(2*math.pi*best.phase)>=0 else -1) if best.mode=='low_swing' else 0)
            if signature!=self.pending:self.pending=signature;self.pending_since=now
            elif now-self.pending_since>=self.c['confirmation_seconds']:
                self.mode_switches+=int(best.mode!=active.mode)
                self.gear_switches+=int(best.gear!=active.gear and best.mode==active.mode)
                self.direction_changes+=int(best.mode!='low_swing' and active.mode!='low_swing' and best.direction!=active.direction)
                if best.mode==active.mode:best.phase+=round(active.phase-best.phase)
                self.active=best.key;active=best;self.switches+=1;self.event='confirmed_boundary_branch'
                self.pending=None;self.pending_since=None
        else:self.pending=None;self.pending_since=None
        self.weak_seconds=0. if active.visual else self.weak_seconds+dt
        self.prune()
        return active
