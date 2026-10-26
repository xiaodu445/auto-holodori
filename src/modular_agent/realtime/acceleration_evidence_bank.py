"""Audio-backed acceleration alternatives with explicit visual entry/exit evidence."""
from collections import deque
from modular_agent.realtime.evidence_recovery_bank import EvidenceRecoveryBank


class AccelerationEvidenceBank(EvidenceRecoveryBank):
    def __init__(self,settings,*args,**kwargs):
        if type(settings.get("acceleration_evidence_policy",False)) is not bool:raise ValueError("invalid acceleration_evidence_policy")
        if not settings.get("guard_speed_commits",False):raise ValueError("acceleration policy requires guarded speed evidence")
        super().__init__(settings,*args,**kwargs)

    def reset(self):
        self.audio_candidates={};self.seeded_acceleration=None;self.acceleration_review=None
        super().reset()

    def reliable_acceleration(self,now):
        cue=self.speed_audio_hint
        return cue if cue and cue.get('motion_hint')=='accelerate' and 0<=now-cue['time']<=1.5 and cue['distance']<=.22 and cue['margin']>=.04 else None

    def advance(self,now):
        dt=super().advance(now)
        active=next((p for p in self.items if p.key==self.active),None)
        cue=self.reliable_acceleration(now)
        if active is None or active.mode=='low_swing' or self.item_stage(active)>=4:
            self.audio_candidates={};return dt
        if cue is None or self.role(active)=='accelerate':return dt
        signature=(cue['time'],active.mode,self.item_stage(active))
        if signature==self.seeded_acceleration:return dt
        self.seeded_acceleration=signature
        existing=[p for p in self.items if p.key!=active.key and p.mode==active.mode and p.epoch==active.epoch and self.item_stage(p)==self.item_stage(active) and self.role(p)=='accelerate']
        if existing:child=max(existing,key=lambda p:p.born)
        else:
            clock=active.rotation_anchor+active.direction*self.profile_warp(active.mode,2).inverse(active.direction*(active.coordinate-active.rotation_anchor)) if self.profile_warp(active.mode,2) is not None else active.coordinate
            clock+=round(active.phase-clock)
            child=self.make(active.mode,clock,2,active.origin,active.score-.015,active.key)
            child.born=now;self.items.append(child)
        # One cue-backed candidate, never all old cohorts. It retains its own clock.
        self.audio_candidates={child.key:dict(expires=cue['time']+1.5,stage=self.item_stage(child),mode=child.mode,cue_time=cue['time'])}
        return dt

    def protected_candidates(self):
        now=self.time if self.time is not None else 0.
        active=next((p for p in self.items if p.key==self.active),None)
        return [p for p in self.items if p.key in self.audio_candidates and self.audio_candidates[p.key]['expires']>now and active is not None and p.epoch==active.epoch and p.mode==active.mode and self.item_stage(p)==self.item_stage(active)]

    def prune(self):
        protected=self.protected_candidates()
        evidence={p.key:self.evidence.get(p.key,deque()) for p in protected}
        speed={p.key:self.speed_evidence.get(p.key,deque()) for p in protected}
        info={p.key:self.branch_info.get(p.key) for p in protected}
        super().prune()
        for p in protected:
            if all(q.key!=p.key for q in self.items):
                removable=next((q for q in reversed(self.items) if q.key!=self.active and q.key not in self.audio_candidates),None)
                if len(self.items)>=self.c['max_hypotheses'] and removable:self.items.remove(removable)
                if len(self.items)<self.c['max_hypotheses']:self.items.append(p)
            if any(q.key==p.key for q in self.items):
                self.evidence[p.key]=evidence[p.key];self.speed_evidence[p.key]=speed[p.key]
                if info[p.key] is not None:self.branch_info[p.key]=info[p.key]
        keys={p.key for p in protected};self.audio_candidates={k:v for k,v in self.audio_candidates.items() if k in keys}

    def correct(self,item,*args):
        if item.key in self.audio_candidates and item.key!=self.active:return
        return super().correct(item,*args)

    def speed_commit_support(self,active,item,now):
        if not super().speed_commit_support(active,item,now):return False
        if active.mode=='low_swing' or item.mode!=active.mode or self.item_stage(active)!=self.item_stage(item) or {self.role(active),self.role(item)}!={'normal','accelerate'}:return True
        cue=self.reliable_acceleration(now)
        # Do not change unrelated skill exits or the separate terminal-stage policy.
        if cue is None or self.item_stage(active)>=4:return True
        entering=self.role(item)=='accelerate'
        span=(.12 if cue else .18) if entering else .30
        minimum=6 if entering else 10
        reference={t:score for t,score,_ in self.speed_evidence.get(active.key,())}
        pairs=[(t,score,good,score-reference[t]) for t,score,good in self.speed_evidence.get(item.key,()) if t in reference]
        good=[r for r in pairs if r[2]]
        mean=sum(r[1] for r in pairs)/len(pairs) if pairs else 0.
        advantage=sum(r[3] for r in pairs)/len(pairs) if pairs else None
        margin=.04 if not entering and cue else .025
        reasons=[]
        if len(good)<minimum or not good or good[-1][0]!=now or good[-1][0]-good[0][0]<span:reasons.append('acceleration_window_incomplete')
        if not pairs or len(good)/len(pairs)<.65:reasons.append('acceleration_support_intermittent')
        if mean<.50 or advantage is None or advantage<=margin:reasons.append('acceleration_visual_advantage_insufficient')
        self.acceleration_review=dict(time=now,from_key=active.key,to_key=item.key,from_role=self.role(active),to_role=self.role(item),from_stage=self.item_stage(active)+1,to_stage=self.item_stage(item)+1,required_span=span,observed_span=good[-1][0]-good[0][0] if good else 0.,paired_frames=len(pairs),supported_frames=len(good),mean_support=mean,advantage=advantage,required_advantage=margin,audio_authorized=bool(cue),reasons=reasons,policy='acceleration_entry_exit')
        self.last_speed_review=self.acceleration_review
        return not reasons

    def switch_requirements(self,active,candidate):
        if candidate.key in self.audio_candidates and self.reliable_acceleration(self.time) and active.mode==candidate.mode and self.item_stage(active)==self.item_stage(candidate) and self.role(candidate)=='accelerate':
            return .025,.12,6
        return super().switch_requirements(active,candidate)

    def legal_successor(self,active,item,now):
        if item.key in self.audio_candidates and self.audio_candidates[item.key]['expires']>now and item.epoch==active.epoch and item.mode==active.mode and self.item_stage(item)==self.item_stage(active):
            # Retention cannot grant a mode/stage change or an unsupported phase jump.
            return abs((item.phase-active.phase+.5)%1-.5)<=.25 and self.speed_commit_support(active,item,now)
        return super().legal_successor(active,item,now)

    def resolve_speed_commit(self,active,best,now,event):
        protected=[p for p in self.protected_candidates() if p.key!=best.key and p.mode==best.mode and self.item_stage(p)==self.item_stage(best)]
        evidence={p.key:self.evidence.get(p.key,deque()) for p in protected}
        speed={p.key:self.speed_evidence.get(p.key,deque()) for p in protected}
        super().resolve_speed_commit(active,best,now,event)
        for p in protected:
            self.items.append(p);self.evidence[p.key]=evidence[p.key];self.speed_evidence[p.key]=speed[p.key]
        self.last_speed_commit['retained_audio_candidates']=[p.key for p in protected]
