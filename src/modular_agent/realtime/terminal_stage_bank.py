"""Final difficulty: a bounded three-role clock bank, no further stage search."""
from collections import deque
from modular_agent.realtime.evidence_recovery_bank import EvidenceRecoveryBank
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank

class TerminalStageBank(EvidenceRecoveryBank):
    def __init__(self,settings,*args,**kwargs):
        if type(settings.get('terminal_stage_strategy',False)) is not bool:raise ValueError('invalid terminal_stage_strategy')
        super().__init__(settings,*args,**kwargs)
    def reset(self):
        super().reset()
        self.terminal_requested=False;self.terminal_locked=False
        self.terminal_review=None;self.terminal_started_at=None;self.terminal_evidence={}

    @property
    def terminal_index(self):return len(self.profiles)-1

    def set_stage(self,index,now,source='badge'):
        result=super().set_stage(index,now,source)
        if index==self.terminal_index:self.terminal_requested=True
        return result

    def record_evidence(self,item,target,quality,moving):
        super().record_evidence(item,target,quality,moving)
        if self.terminal_locked:
            # Unlike pre-final stage confirmation, visibility gaps do not
            # reset the clock or pretend missing frames are negative evidence.
            records=self.terminal_evidence.setdefault(item.key,deque())
            records.append((self.time,float(target),bool(item.visual and item.turn_supported and quality>=.55 and moving>=.08)))
            while records and self.time-records[0][0]>.8:records.popleft()

    def prune(self):
        if not getattr(self,'terminal_locked',False):return super().prune()
        active=next((p for p in self.items if p.key==self.active),None)
        circles=[p for p in self.items if p.mode!='low_swing' and self.item_stage(p)==self.terminal_index and p.epoch==self.epoch]
        groups={}
        # Keep the newest landing and one independent earlier clock per role.
        for p in circles:groups.setdefault((p.mode,p.gear),[]).append(p)
        keep=[]
        for group in groups.values():
            newest=max(group,key=lambda p:(p.born,p.score));keep.append(newest)
            older=[p for p in group if p.key!=newest.key]
            if older:keep.append(max(older,key=lambda p:p.score))
        low=[p for p in self.items if p.mode=='low_swing' and p.epoch==self.epoch and (p.key==self.active or self.time-p.born<=self.c.get('transition_evidence_window',.75))]
        keep+=low
        if active and active not in keep:keep.append(active)
        self.items=sorted(keep,key=lambda p:(p.key==self.active,p.score),reverse=True)[:self.c['max_hypotheses']]
        keys={p.key for p in self.items}
        self.branch_info={k:v for k,v in self.branch_info.items() if k in keys}
        self.evidence={k:v for k,v in self.evidence.items() if k in keys}
        self.terminal_evidence={k:v for k,v in self.terminal_evidence.items() if k in keys}
        self.stage_candidates=set()

    def terminal_support(self,active,item,now):
        reference={t:(score,good) for t,score,good in self.terminal_evidence.get(active.key,())}
        rows=[(t,score,good,reference[t]) for t,score,good in self.terminal_evidence.get(item.key,()) if t in reference]
        good=[r for r in rows if r[2]]
        # Compare common observable times; simultaneous total occlusion carries
        # no information about which speed is right. Do not extrapolate a score.
        observed=[r for r in rows if r[2] or r[3][1]]
        advantage=sum(r[1]-r[3][0] for r in observed)/len(observed) if observed else None
        rivals=[]
        for p in self.items:
            if p.key in (active.key,item.key) or p.mode!=item.mode or p.gear==item.gear:continue
            evidence={t:(score,supported) for t,score,supported in self.terminal_evidence.get(p.key,())}
            pairs=[r[1]-evidence[r[0]][0] for r in observed if r[0] in evidence and (r[2] or evidence[r[0]][1])]
            if len(pairs)>=6:rivals.append(sum(pairs)/len(pairs))
        cue=self.speed_audio_hint
        authorized=bool(cue and cue.get('motion_hint')==self.role(item) and 0<=now-cue['time']<=1.5 and cue['distance']<=.22 and cue['margin']>=.04)
        span=.18 if authorized else .30
        reasons=[]
        if len(good)<8 or not good or good[-1][0]!=now or good[-1][0]-good[0][0]<span:reasons.append('visible_window_incomplete')
        if advantage is None or advantage<=.025:reasons.append('paired_advantage_insufficient')
        if not good or sum(r[1] for r in good)/len(good)<.55:reasons.append('absolute_support_insufficient')
        separation=min(rivals) if rivals else None
        if separation is not None and separation<.015:reasons.append('fixed_roles_ambiguous')
        self.terminal_review=dict(time=now,from_key=active.key,to_key=item.key,visible_frames=len(good),observable_pairs=len(observed),required_span=span,advantage=advantage,runner_separation=separation,audio_authorized=authorized,reasons=reasons)
        return not reasons

    def legal_successor(self,active,item,now):
        if not self.terminal_locked:return super().legal_successor(active,item,now)
        if self.item_stage(item)!=self.terminal_index:return False
        if active.mode!='low_swing' and item.mode==active.mode:
            if self.role(item)=='decelerate' and self.profile_status(item)=='pending_calibration' and self.c.get('uncalibrated_decelerate_diagnostic_only',False):return False
            if item.gear==active.gear:return False
            return item.epoch==self.epoch and self.terminal_support(active,item,now)
        # Preserve the same legal three modes and directional low-swing exit.
        return super().legal_successor(active,item,now)

    def choose(self,now,dt,compatible=None):
        if not self.terminal_locked:
            selected=super().choose(now,dt,compatible)
            if self.terminal_requested and selected is not None and self.item_stage(selected)==self.terminal_index:
                self.terminal_locked=True;self.terminal_started_at=now;self.terminal_evidence={}
                self.stage_candidates=set();self.items=[p for p in self.items if self.item_stage(p)==self.terminal_index]
            return selected
        # Landing layer still confirms modes. Its circle speed paths all pass
        # terminal_support; the inherited short recovery path is bypassed.
        prior=next((p for p in self.items if p.key==self.active),None)
        selected=LandingTrajectoryBank.choose(self,now,dt,compatible)
        if selected is None or selected.mode=='low_swing':return selected
        if prior and selected.key!=prior.key:
            if selected.mode==prior.mode:self.record_terminal_commit(prior,selected,now)
            return selected
        candidates=[p for p in self.items if p.key!=selected.key and p.mode==selected.mode and p.gear!=selected.gear and p.visual and self.legal_successor(selected,p,now) and (compatible is None or compatible(selected,p))]
        if not candidates:return selected
        best=max(candidates,key=lambda p:self.terminal_review_for(selected,p,now))
        self.active=best.key;self.switches+=1;self.gear_switches+=1
        self.pending=None;self.pending_since=None
        self.record_terminal_commit(selected,best,now)
        # A speed choice keeps the other two fixed-role clocks alive; mode
        # changes still clear the old episode through commit_episode.
        return best

    def record_terminal_commit(self,active,best,now):
        self.terminal_support(active,best,now)
        reference={t:score for t,score,_ in self.terminal_evidence.get(active.key,())}
        paired=[dict(time=t,support=score,good=good,incumbent_support=reference[t]) for t,score,good in self.terminal_evidence.get(best.key,()) if t in reference]
        self.last_speed_commit=dict(time=now,event='confirmed_terminal_speed_role',from_key=active.key,to_key=best.key,from_role=self.role(active),to_role=self.role(best),from_stage=self.terminal_index+1,to_stage=self.terminal_index+1,paired_evidence=paired,guard_review=dict(self.terminal_review))
        self.event='confirmed_terminal_speed_role'

    def terminal_review_for(self,active,item,now):
        self.terminal_support(active,item,now)
        return self.terminal_review['advantage']
