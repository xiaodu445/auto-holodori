"""Evidence-window adoption for same-mode speed and stage alternatives."""
from modular_agent.realtime.coexisting_stage_bank import CoexistingStageBank

class EvidenceRecoveryBank(CoexistingStageBank):
    def switch_requirements(self,active,candidate):
        if not self.c.get('half_cycle_switch_policy',False):return self.c.get('recovery_window_margin',.008),.12,6
        # Clock progress follows direction from the common ground crossing;
        # reverse motion must not use screen height or forward phase ordering.
        progress=(active.direction*(active.phase-self.boundary))%1
        return (.025,.18,8) if progress<.5 else (.005,.12,6)
    def legal_successor(self,active,item,now):
        if not super().legal_successor(active,item,now):return False
        if self.c.get('long_speed_window',False) and active.mode!='low_swing' and item.mode==active.mode and (item.gear!=active.gear or self.item_stage(item)!=self.item_stage(active)):
            return self.long_speed_support(active,item,now)
        if not self.c.get('half_cycle_switch_policy',False) or active.mode=='low_swing' or item.mode!=active.mode or item.gear==active.gear:return True
        margin,span,frames=self.switch_requirements(active,item)
        good=[r for r in self.evidence.get(item.key,()) if r[2]]
        advantage=self.branch_advantage(active,item)
        return len(good)>=frames and good[-1][0]==now and good[-1][0]-good[0][0]>=span and advantage is not None and advantage>margin
    def choose(self,now,dt,compatible=None):
        selected=super().choose(now,dt,compatible)
        if selected is None:return None
        if selected.mode=="low_swing":return selected
        candidates=[]
        for p in self.items:
            if p.key==selected.key or p.mode!=selected.mode or not p.visual:continue
            if not self.speed_commit_support(selected,p,now):continue
            stage_branch=p.key in self.stage_candidates
            if not stage_branch and p.gear==selected.gear:continue
            if not stage_branch and not self.legal_successor(selected,p,now):continue
            if self.item_stage(p)<self.item_stage(selected):continue
            if self.role(p)=='decelerate' and self.profile_status(p)=='pending_calibration':continue
            if compatible is not None and not compatible(selected,p):continue
            good=[r for r in self.evidence.get(p.key,()) if r[2]]
            advantage=self.branch_advantage(selected,p)
            if self.c.get('long_speed_window',False):
                if not self.long_speed_support(selected,p,now):continue
                candidates.append(p);continue
            margin,span,frames=(.025,.12,6) if stage_branch else self.switch_requirements(selected,p)
            if len(good)<frames or good[-1][0]!=now or good[-1][0]-good[0][0]<span or advantage is None or advantage<=margin:continue
            # Single-frame superiority is insufficient; keep the independent
            # candidate clock instead of replacing it with the failed incumbent.
            if sum(r[1] for r in good)/len(good)<.45:continue
            candidates.append(p)
        if not candidates:return selected
        best=max(candidates,key=lambda p:self.branch_advantage(selected,p))
        previous_stage=self.item_stage(selected);next_stage=self.item_stage(best)
        self.active=best.key;self.switches+=1;self.gear_switches+=int(best.gear!=selected.gear)
        self.stage_index=next_stage;self.c.update(self.rates(next_stage))
        self.last_recovery=dict(time=now,from_stage=previous_stage+1,to_stage=next_stage+1,from_key=selected.key,to_key=best.key,advantage=self.branch_advantage(selected,best))
        # Any accepted speed-stage/role correction resolves its old cohort.
        self.resolve_speed_commit(selected,best,now,'confirmed_temporal_speed_recovery')
        self.event='confirmed_temporal_speed_recovery'
        return best
