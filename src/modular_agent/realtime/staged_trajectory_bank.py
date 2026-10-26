"""Stage-scoped four-role speed templates; signed direction remains independent."""
import math
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
from modular_agent.realtime.trajectory_bank import DirectionWarp


class StagedTrajectoryBank(LandingTrajectoryBank):
    def __init__(self,settings,boundary,swing_entry,profiles):
        for flag in ['stage_profile_shapes','uncalibrated_decelerate_diagnostic_only']:
            if type(settings.get(flag,False)) is not bool:raise ValueError('invalid '+flag)
        self.fixed_rotation_gears=list(settings['rotation_gears']) if settings.get('stage_swing_only',False) else None
        self.fixed_initial_rate=settings.get('initial_rotation_rate',settings['rotation_gears'][0])
        self.profiles=profiles['stages']
        self.profile_shapes=settings.get('stage_profile_shapes',False)
        self.stage_warps=[{role:{mode:DirectionWarp(data) for mode,data in branch.get('directions',{}).items()} for role,branch in stage['branches'].items()} for stage in self.profiles] if self.profile_shapes else []
        if len(self.profiles)<2:raise ValueError('missing difficulty stages')
        for stage in self.profiles:
            rates=[stage['branches'][name]['clock_rate'] for name in ['decelerate','normal','accelerate','low_swing']]
            if any(type(r) not in (int,float) or not math.isfinite(r) or r<=0 for r in rates) or not rates[0]<rates[1]<rates[2]:raise ValueError('invalid stage rates')
        initial=dict(settings);initial.update(self.rates(0));initial['initial_rotation_rate']=self.fixed_initial_rate if self.fixed_rotation_gears is not None else initial['rotation_gears'][1]
        super().__init__(initial,boundary,swing_entry)
    def reset(self):
        super().reset();self.c.update(self.rates(0));self.c['initial_rotation_rate']=self.fixed_initial_rate if self.fixed_rotation_gears is not None else self.c['rotation_gears'][1];self.stage_index=0;self.stage_confirmed=False;self.last_stage_change=None
    def profile_warp(self,mode,gear):
        if not self.profile_shapes or mode=='low_swing':return self.warp if mode=='low_swing' else self.reverse_warp if mode=='rotation_reverse' else None
        role=['decelerate','normal','accelerate'][gear]
        return self.stage_warps[self.stage_index][role].get(mode,self.reverse_warp if mode=='rotation_reverse' else None)
    def make(self,*args,**kwargs):
        p=super().make(*args,**kwargs)
        if self.profile_shapes and p.mode!='low_swing':p.warp=self.profile_warp(p.mode,p.gear)
        return p
    def rotation_clock(self,mode,coordinate,gear=None):
        if not self.profile_shapes:return super().rotation_clock(mode,coordinate,gear)
        if gear is None:
            active=next((p for p in self.items if p.key==self.active and p.mode==mode),None)
            gear=active.gear if active is not None else 1
        warp=self.profile_warp(mode,gear)
        if warp is None:return coordinate
        direction=-1 if mode=='rotation_reverse' else 1
        clock=self.boundary+direction*warp.inverse(direction*(coordinate-self.boundary))
        return clock+round(coordinate-clock)
    def profile_status(self,item):
        if self.fixed_rotation_gears is not None:return 'unverified_shared_slots'
        role=self.role(item);return self.profiles[self.stage_index]['branches'][role].get('status','pending_calibration')
    def rates(self,index):
        branches=self.profiles[index]['branches']
        return dict(rotation_gears=list(self.fixed_rotation_gears) if self.fixed_rotation_gears is not None else [branches[name]['clock_rate'] for name in ['decelerate','normal','accelerate']],swing_gears=[branches['low_swing']['clock_rate']])
    def set_stage(self,index,now,source='badge'):
        if type(index) is not int or not 0<=index<len(self.profiles) or not math.isfinite(now) or self.time is not None and now<self.time:raise ValueError('invalid stage hint')
        if index<self.stage_index:return False
        self.stage_confirmed=True
        if index==self.stage_index:return False
        previous_stage=self.stage_index
        old_coordinates={p.key:p.coordinate for p in self.items} if self.profile_shapes else {}
        old={k:list(self.c[k]) for k in ('rotation_gears','swing_gears')};new=self.rates(index)
        for item in self.items:
            key='swing_gears' if item.mode=='low_swing' else 'rotation_gears'
            item.speed*=new[key][item.gear]/old[key][item.gear]
        if self.profile_shapes:
            self.stage_index=index
            for p in self.items:
                if p.mode=='low_swing':continue
                p.warp=self.profile_warp(p.mode,p.gear);clock=self.rotation_clock(p.mode,old_coordinates[p.key],p.gear);p.phase=clock+round(p.phase-clock)
        self.c.update(new);self.c['initial_rotation_rate']=self.fixed_initial_rate if self.fixed_rotation_gears is not None else new['rotation_gears'][1]
        # The global difficulty cue changes every role together. Preserve curve
        # phase/direction/episode, discard evidence about the obsolete speed set.
        active=next((p for p in self.items if p.key==self.active),None)
        keep_circle=self.fixed_rotation_gears is not None and self.c.get('preserve_circle_stage_evidence',False) and active is not None and active.mode!='low_swing'
        if keep_circle:
            self.items=[p for p in self.items if p.mode!='low_swing']
            keys={p.key for p in self.items}
            self.branch_info={k:v for k,v in self.branch_info.items() if k in keys}
            self.evidence={k:v for k,v in self.evidence.items() if k in keys}
            if self.pending is not None and self.pending[0]=='low_swing':self.pending=None;self.pending_since=None
        else:
            if active is not None:self.items=[active]
            self.branch_info={};self.evidence={};self.pending=None;self.pending_since=None
        self.last_stage_change=dict(time=now,from_stage=previous_stage+1,to_stage=index+1,source=source)
        self.stage_index=index;return True
    def acquire(self,phase,now,direction=1):
        if self.c.get('initial_stage_forward_only',False) and self.stage_confirmed and self.stage_index==0:direction=1
        result=super().acquire(phase,now,direction)
        if self.profile_shapes:
            for p in self.items:p.phase=self.rotation_clock(p.mode,phase,p.gear)
        return result
    def legal_successor(self,active,item,now):
        if self.profile_shapes and self.c.get('uncalibrated_decelerate_diagnostic_only',False) and item.mode!='low_swing' and self.role(item)=='decelerate' and self.profile_status(item)=='pending_calibration':return False
        if self.c.get('initial_stage_forward_only',False) and self.stage_confirmed and self.stage_index==0 and item.mode=='rotation_reverse':return False
        return super().legal_successor(active,item,now)
    def role(self,item):
        if self.fixed_rotation_gears is not None and item.mode!='low_swing':return 'rotation_slot_'+str(item.gear)
        return 'low_swing' if item.mode=='low_swing' else ['decelerate','normal','accelerate'][item.gear]
