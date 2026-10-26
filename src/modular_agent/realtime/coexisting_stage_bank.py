"""Count-stage hints create alternatives; they never retime active playback."""
from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank

class CoexistingStageBank(StagedTrajectoryBank):
    def __init__(self,settings,*args,**kwargs):
        if type(settings.get('guard_speed_commits',False)) is not bool:raise ValueError('invalid guard_speed_commits')
        super().__init__(settings,*args,**kwargs)
    def reset(self):
        self.visible_speed_authority=None;self.item_stages={};self.stage_candidates=set();self.creating_stage=None;self.speed_evidence={};self.last_speed_commit=None;self.last_speed_review=None;self.speed_audio_hint=None
        super().reset();self.count_stage_index=0
    def item_stage(self,item):
        return self.item_stages.get(item.key,self.stage_index)
    def make(self,*args,**kwargs):
        p=super().make(*args,**kwargs)
        self.item_stages[p.key]=self.stage_index
        return p
    def bounds(self,item):
        authority=getattr(self,'visible_speed_authority',None)
        if self.c.get('visible_fragment_priority',False) and authority and 'rate' in authority and item.key==self.active and authority['epoch']==self.epoch and authority['mode']==item.mode and authority['stage']==self.item_stage(item) and authority['gear']==item.gear:
            return authority['rate']*.94,authority['rate']*1.06
        stage=self.item_stage(item);key='swing_gears' if item.mode=='low_swing' else 'rotation_gears'
        center=self.rates(stage)[key][item.gear]
        tolerance=self.c.get('swing_gear_tolerance',self.c['gear_tolerance']) if item.mode=='low_swing' else self.c['gear_tolerance']
        return center*(1-tolerance),center*(1+tolerance)
    def profile_status(self,item):
        return self.profiles[self.item_stage(item)]['branches'][self.role(item)].get('status','pending_calibration')
    def set_stage(self,index,now,source='badge'):
        import math
        if type(index) is not int or not 0<=index<len(self.profiles) or not math.isfinite(now) or self.time is not None and now<self.time:raise ValueError('invalid stage hint')
        if index<=self.count_stage_index:return False
        previous=self.count_stage_index;self.count_stage_index=index;self.stage_confirmed=True
        self.last_stage_change=dict(time=now,from_stage=previous+1,to_stage=index+1,source=source,policy='coexisting_speed_stages')
        if not self.items:
            self.stage_index=index;self.c.update(self.rates(index));return True
        self.spawn_stage_candidates(now)
        return True
    def force_count_stage(self,index,now):
        """Explicit count boundary retimes the active role without changing motion."""
        active=next((p for p in self.items if p.key==self.active),None)
        if active is not None:
            self.stage_index=self.item_stage(active);self.c.update(self.rates(self.stage_index))
        if self.stage_index>=index:return False
        # Remove mixed-stage alternatives before the parent's global retiming.
        if active is not None:self.items=[active]
        changed=StagedTrajectoryBank.set_stage(self,index,now,source='count_30_forced')
        self.count_stage_index=max(self.count_stage_index,index)
        self.item_stages={p.key:index for p in self.items};self.stage_candidates=set()
        self.speed_evidence={};self.last_speed_commit=None;self.last_speed_review=None
        if hasattr(self,'audio_candidates'):self.audio_candidates={}
        for p in self.items:
            key='swing_gears' if p.mode=='low_swing' else 'rotation_gears'
            p.speed=self.rates(index)[key][p.gear]
        return changed
    def spawn_stage_candidates(self,now):
        active=next((p for p in self.items if p.key==self.active),None)
        if active is None or self.count_stage_index<=self.item_stage(active):return
        # Replace expired alternatives, never the incumbent or its motion clock.
        self.items=[p for p in self.items if p.key not in self.stage_candidates];self.stage_candidates=set()
        prior=self.stage_index;old=self.rates(prior);self.stage_index=self.count_stage_index;self.c.update(self.rates(self.stage_index))
        try:
            for gear in range(len(self.gears(active.mode))):
                clock=self.rotation_clock(active.mode,active.coordinate,gear) if active.mode!='low_swing' else active.phase
                clock+=round(active.phase-clock)
                p=self.make(active.mode,clock,gear,active.origin,active.score-.015,active.key)
                p.born=now;self.items.append(p);self.stage_candidates.add(p.key)
        finally:self.stage_index=prior;self.c.update(old)
    def advance(self,now):
        active=next((p for p in self.items if p.key==self.active),None)
        if active is not None:
            self.stage_index=self.item_stage(active);self.c.update(self.rates(self.stage_index))
        result=super().advance(now)
        if self.count_stage_index>self.stage_index and not any(p.key in self.stage_candidates for p in self.items):self.spawn_stage_candidates(now)
        return result
    def prune(self):
        # Keep each pending-stage role even if an old-stage role has the same gear.
        pending=[p for p in self.items if p.key in self.stage_candidates and self.time is not None and self.time-p.born<=self.c.get('stage_candidate_lifetime',1.5)]
        pending_evidence={p.key:self.evidence[p.key] for p in pending if p.key in self.evidence}
        self.items=[p for p in self.items if p.key not in self.stage_candidates]
        super().prune()
        self.evidence.update(pending_evidence)
        self.items=self.items[:max(1,self.c['max_hypotheses']-len(pending))]+pending
        self.stage_candidates={p.key for p in pending}
    def correct(self,item,*args):
        if item.key in self.stage_candidates:return
        return super().correct(item,*args)
    def legal_successor(self,active,item,now):
        if item.key in self.stage_candidates:return False # selected only by paired temporal evidence below
        if self.item_stage(item)!=self.item_stage(active):return False
        if not self.speed_commit_support(active,item,now):return False
        return super().legal_successor(active,item,now)
    def record_evidence(self,item,target,quality,moving):
        super().record_evidence(item,target,quality,moving)
        if self.c.get('guard_speed_commits',False):
            from collections import deque
            records=self.speed_evidence.setdefault(item.key,deque())
            records.append(self.evidence[item.key][-1])
            while records and self.time-records[0][0]>.5:records.popleft()
            keys={p.key for p in self.items}
            self.speed_evidence={k:v for k,v in self.speed_evidence.items() if k in keys}

    def speed_commit_support(self,active,item,now):
        """Compare simultaneous visual evidence for ambiguous skill/stage changes."""
        authority=getattr(self,'visible_speed_authority',None)
        if self.c.get('visible_fragment_priority',False) and authority and 0<=now-authority['time']<=.5 and authority['epoch']==self.epoch and authority['mode']==active.mode==item.mode and authority['stage']==self.item_stage(active)==self.item_stage(item) and active.gear==authority['gear'] and item.gear!=authority['gear']:
            self.last_speed_review=dict(time=now,from_key=active.key,to_key=item.key,reasons=['trusted_visible_speed_has_priority'])
            return False
        if not self.c.get('guard_speed_commits',False) or active.mode=='low_swing' or item.mode!=active.mode:return True
        cross_stage=self.item_stage(active)!=self.item_stage(item)
        role_change=self.role(active)!=self.role(item)
        active_rate=self.rates(self.item_stage(active))['rotation_gears'][active.gear]
        candidate_rate=self.rates(self.item_stage(item))['rotation_gears'][item.gear]
        close_rates=abs(active_rate-candidate_rate)/max(active_rate,candidate_rate)<.03
        sensitive=(self.role(active)=='decelerate' and role_change) or {self.role(active),self.role(item)}=={'decelerate','accelerate'} or cross_stage or (role_change and close_rates)
        if not sensitive:return True
        cue=getattr(self,'speed_audio_hint',None)
        authorized=bool(cue and cue.get('motion_hint')==self.role(item) and 0<=now-cue['time']<=1.5 and cue['distance']<=.22 and cue['margin']>=.04)
        span=.18 if authorized else .30
        reference={t:score for t,score,_ in self.speed_evidence.get(active.key,())}
        paired=[(t,score,good,score-reference[t]) for t,score,good in self.speed_evidence.get(item.key,()) if t in reference]
        good=[r for r in paired if r[2]]
        mean=sum(r[1] for r in paired)/len(paired) if paired else 0.
        advantage=sum(r[3] for r in paired)/len(paired) if paired else None
        rivals=[]
        for p in self.items:
            if p.key in (active.key,item.key) or p.mode!=item.mode or (self.item_stage(p)==self.item_stage(item) and self.role(p)==self.role(item)):continue
            evidence={t:score for t,score,_ in self.speed_evidence.get(p.key,())}
            differences=[score-evidence[t] for t,score,_,_ in paired if t in evidence]
            if len(differences)>=6:rivals.append(sum(differences)/len(differences))
        separation=min(rivals) if rivals else None
        reasons=[]
        if len(good)<10 or not good or good[-1][0]!=now or good[-1][0]-good[0][0]<span:reasons.append('paired_window_incomplete')
        if not paired or len(good)/len(paired)<.65:reasons.append('intermittent_support')
        if mean<.45 or advantage is None or advantage<=.025:reasons.append('paired_support_insufficient')
        if separation is not None and separation<.015:reasons.append('competing_clock_ambiguous')
        self.last_speed_review=dict(time=now,from_key=active.key,to_key=item.key,from_role=self.role(active),to_role=self.role(item),from_stage=self.item_stage(active)+1,to_stage=self.item_stage(item)+1,required_span=span,observed_span=good[-1][0]-good[0][0] if good else 0.,paired_frames=len(paired),supported_frames=len(good),mean_support=mean,advantage=advantage,runner_separation=separation,audio_authorized=authorized,reasons=reasons)
        return not reasons

    def resolve_speed_commit(self,active,best,now,event):
        # Preserve winner evidence before destructive cohort resolution.
        reference={t:score for t,score,_ in self.evidence.get(active.key,())}
        paired=[dict(time=t,support=score,good=good,incumbent_support=reference[t]) for t,score,good in self.evidence.get(best.key,()) if t in reference]
        self.speed_commit_support(active,best,now)
        review=getattr(self,'last_speed_review',None)
        review=review if review and review['time']==now and review['from_key']==active.key and review['to_key']==best.key else None
        self.last_speed_commit=dict(guard_review=review,time=now,event=event,from_key=active.key,to_key=best.key,from_role=self.role(active),to_role=self.role(best),from_stage=self.item_stage(active)+1,to_stage=self.item_stage(best)+1,paired_evidence=paired)
        self.items=[best];self.stage_candidates=set();self.branch_info={};self.evidence={};self.pending=None;self.pending_since=None

    def long_speed_support(self,active,item,now):
        """One evidence rule shared by ordinary, stage and recovery paths."""
        span=max(.25,min(.45,.45/max(active.speed,item.speed)))
        records=list(self.evidence.get(item.key,()))
        good=[r for r in records if r[2]]
        advantage=self.branch_advantage(active,item)
        mean=sum(r[1] for r in good)/len(good) if good else 0.
        rivals=[]
        for p in self.items:
            if p.key in (item.key,active.key) or p.mode!=item.mode or self.role(p)==self.role(item):continue
            g=[r for r in self.evidence.get(p.key,()) if r[2]]
            if len(g)>=6:rivals.append(sum(r[1] for r in g)/len(g))
        separation=mean-max(rivals) if rivals else 1.
        reasons=[]
        if len(good)<12:reasons.append('too_few_supported_frames')
        if not good or good[-1][0]!=now or good[-1][0]-good[0][0]<span:reasons.append('evidence_window_incomplete')
        if not records or len(good)/len(records)<.65:reasons.append('support_too_intermittent')
        if advantage is None or advantage<=.025:reasons.append('incumbent_advantage_insufficient')
        if mean<.60:reasons.append('absolute_support_insufficient')
        if separation<.025:reasons.append('role_candidates_ambiguous')
        snapshot=dict(time=now,from_key=active.key,to_key=item.key,required_span=span,observed_span=good[-1][0]-good[0][0] if good else 0.,supported_frames=len(good),mean_support=mean,advantage=advantage,runner_separation=separation,reasons=reasons)
        self.last_speed_review=snapshot
        return not reasons

    def choose(self,now,dt,compatible=None):
        selected=super().choose(now,dt,compatible)
        if selected is None:return None
        candidates=[]
        for p in self.items:
            if p.key not in self.stage_candidates or not p.visual:continue
            if not self.speed_commit_support(selected,p,now):continue
            if self.role(p)=='decelerate' and self.profile_status(p)=='pending_calibration':continue
            good=[r for r in self.evidence.get(p.key,()) if r[2]]
            advantage=self.branch_advantage(selected,p)
            supported=self.long_speed_support(selected,p,now) if self.c.get('long_speed_window',False) else len(good)>=6 and good[-1][0]==now and good[-1][0]-good[0][0]>=.12 and advantage is not None and advantage>.025
            if supported:candidates.append(p)
        if candidates:
            best=max(candidates,key=lambda p:self.branch_advantage(selected,p))
            self.active=best.key;self.switches+=1;self.stage_index=self.item_stage(best);self.c.update(self.rates(self.stage_index))
            self.resolve_speed_commit(selected,best,now,'confirmed_speed_stage_branch')
            self.event='confirmed_speed_stage_branch';selected=best
        return selected
