"""Causal mask-to-template clock, with bounded missing-observation continuation."""
from collections import deque
import hashlib
import json
import math
from itertools import permutations
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate

class JumpClock:
    def __init__(self,config):
        self.c=config;self.x=np.linspace(.25,.81,37);self.grid=np.arange(128)/128
        catalog=json.loads((ROOT/config['catalog']).read_text(encoding='utf-8'))
        self.templates=[]
        for entry in catalog['templates']:
            if config['stage'] and entry['stage']!=config['stage']:continue
            p=ROOT/entry['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256']
            data=json.loads(p.read_text(encoding='utf-8'))
            override=config.get('jump_progress_nodes_by_template',{}).get(data['template_id'])
            if override is not None:
                if len(override)!=len(data['jump_progress_nodes']) or any(not math.isfinite(v) or not 0<=v<1 for v in override):raise ValueError('Invalid jump phase override')
                data['jump_progress_nodes']=list(override)
            self.templates.append(TimedRopeTemplate(data))
        if not self.templates:raise ValueError('No templates for selected stage')
        # Different source versions describe the same state with different phase anchors.
        # Keep one per context so switching source versions cannot manufacture motion changes.
        priority={'human_observed_cycle':4,'automatic_visible_cycle':3,'borrowed_reverse_cycle_time_scaled':2,'legacy_shape_and_warp_compiled_to_time':1}
        chosen={}
        for t in self.templates:
            if t.context not in chosen or priority.get(t.data['source_kind'],0)>priority.get(chosen[t.context].data['source_kind'],0):chosen[t.context]=t
        self.templates=list(chosen.values())
        self.curves=np.array([[t.curve(u,self.x) for u in self.grid] for t in self.templates])
        self.active_stage=config['stage'] or 1
        self.reset()

    def onset_windows(self,template):
        targets=[float(v) for v in template.data['jump_progress_nodes']]
        directions=['rotation']*len(targets)
        if template.context[1]=='low_swing':
            directions=['unknown']*len(targets)
            prior=template.data.get('prior_shape_onset_nodes')
            if len(targets)==2 and prior is not None and len(prior)==2:
                # The source compiler records prior nodes as increasing/decreasing
                # swing coordinate, while manual calibration may sort the new nodes.
                mapping=min(permutations(range(2)),key=lambda p:sum(abs((targets[p[i]]-prior[i]+.5)%1-.5) for i in range(2)))
                directions[mapping[0]]='back_to_front';directions[mapping[1]]='front_to_back'
            elif len(targets)==2 and template.data.get('source_kind')=='legacy_shape_and_warp_compiled_to_time':
                directions=['back_to_front','front_to_back']
        extra=float(self.c.get('low_swing_back_to_front_extra_early_seconds_by_stage',{}).get(str(template.context[0]),0))
        if not math.isfinite(extra) or not 0<=extra<=.3:raise ValueError('Low-swing extra early window must be between 0 and .3 seconds')
        stage_extra=float(self.c.get('extra_early_seconds_by_stage',{}).get(str(template.context[0]),0))
        if not math.isfinite(stage_extra) or not 0<=stage_extra<=.3:raise ValueError('Stage extra early window must be between 0 and .3 seconds')
        return [dict(phase=target,direction=direction,extra_early_seconds=stage_extra+(extra if direction=='back_to_front' else 0.),dispatch_window_seconds=self.c['dispatch_window_seconds']+stage_extra+(extra if direction=='back_to_front' else 0.)) for target,direction in zip(targets,directions)]

    def onset_decision(self,template,phase,elapsed=0.):
        windows=self.onset_windows(template);late=self.c['late_window_seconds']
        arrivals=[((w['phase']-phase-elapsed/template.period)%1)*template.period for w in windows]
        arrivals=[eta-template.period if eta>template.period-late else eta for eta in arrivals]
        if not arrivals:return None
        due=[i for i,eta in enumerate(arrivals) if -late<=eta<=windows[i]['dispatch_window_seconds']]
        chosen=min(due,key=lambda i:arrivals[i]) if due else int(np.argmin(arrivals))
        return dict(eta=arrivals[chosen],due=bool(due),onset_index=chosen,**windows[chosen])

    def set_stage(self,stage):
        if stage!=self.active_stage:
            self.active_stage=stage;self.reset()

    def reset(self):
        self.cost=np.zeros((len(self.templates),len(self.grid)));self.last=None
        self.selected=None;self.phase=None;self.last_seen=None
        self.pending=None;self.jumps=0

    def features(self,mask,full_shape,roi):
        h,w=full_shape[:2];x0,y0,x1,y1=roi;y=np.full(len(self.x),np.nan)
        for i,x in enumerate(self.x):
            col=round(x*w)-x0
            if not 0<=col<mask.shape[1]:continue
            pixels=np.flatnonzero(mask[:,max(0,col-1):min(mask.shape[1],col+2)].any(1))
            if not len(pixels):continue
            runs=np.split(pixels,np.where(np.diff(pixels)>1)[0]+1)
            run=max(runs,key=len)
            if len(run)>self.c['max_rope_thickness_fraction']*h:continue
            y[i]=(float(np.median(run))+y0)/h
        return y

    def matching_settings(self):
        matching=dict(self.c)
        matching.update(self.c.get('matching_overrides_by_stage', {}).get(str(self.active_stage), {}))
        if self.selected is not None:
            context=self.templates[self.selected].context
            if context[0]==self.active_stage:
                key=f'{context[0]}:{context[1]}'
                matching.update(self.c.get('matching_overrides_by_context', {}).get(key, {}))
        return matching

    def update(self,now,mask,full_shape,roi,dispatch_time=None):
        matching=self.matching_settings()
        dt=0 if self.last is None else now-self.last
        if dt<0:raise ValueError('Nonmonotonic observation timestamp')
        if dt>self.c['reset_gap_seconds']:self.reset();dt=0
        self.last=now;y=self.features(mask,full_shape,roi);seen=np.isfinite(y)
        # Transport accumulated evidence at each template's own speed; no future frames.
        for i,t in enumerate(self.templates):
            self.cost[i]=np.interp((self.grid-dt/t.period)%1,np.r_[self.grid,1],np.r_[self.cost[i],self.cost[i,0]])
        if self.phase is not None:self.phase=(self.phase+dt/self.templates[self.selected].period)%1
        valid=np.isfinite(self.curves)&seen
        counts=valid.sum(2);distance=np.where(valid,np.minimum(abs(self.curves-y),.10),0)
        loss=np.divide(distance.sum(2),counts,out=np.full(counts.shape,.10),where=counts>=matching['minimum_columns'])
        allowed=np.array([t.context[0]==self.active_stage for t in self.templates])
        loss[~allowed]=1.
        if not allowed.any():
            return dict(trigger=False,status='unsupported_stage',columns=int(seen.sum()),missing_seconds=None,phase=None,template=None,eta=None,jumps=self.jumps,feature_y=[])
        observed=int(seen.sum())>=matching['minimum_columns']
        candidate_template=None;candidate_phase=None;candidate_error=None;candidate_margin=None
        if observed:
            alpha=1-math.exp(-max(dt,1/60)/.12)
            self.cost=(1-alpha)*self.cost+alpha*loss
            winner=int(np.argmin(self.cost)//len(self.grid));j=int(self.cost[winner].argmin())
            candidate=float(self.grid[j]);error=float(loss[winner,j])
            candidate_template=self.templates[winner].key;candidate_phase=candidate;candidate_error=error
            costs=np.sort(self.cost.min(axis=1)[allowed]);candidate_margin=float(costs[1]-costs[0]) if len(costs)>1 else None
            if error<=matching['max_shape_error']:
                if self.selected is None:
                    self.selected=winner;self.phase=candidate
                else:
                    gap=abs((candidate-self.phase+.5)%1-.5)
                    if winner==self.selected and gap<=self.c['max_phase_correction']:
                        self.phase=candidate;self.pending=None
                    else:
                        key=winner
                        if self.pending is None or self.pending[0]!=key:self.pending=(key,now)
                        elif now-self.pending[1]>=self.c['switch_confirmation_seconds']:
                            self.selected=winner;self.phase=candidate;self.pending=None
                # Only a matching observation of the currently accepted clock renews support.
                accepted_j=int(round(self.phase*len(self.grid)))%len(self.grid)
                if loss[self.selected,accepted_j]<=matching['max_shape_error']:self.last_seen=now
        missing=None if self.last_seen is None else now-self.last_seen
        report=dict(matching_thresholds={k:matching[k] for k in ('minimum_columns','max_shape_error','max_predict_seconds')},trigger=False,status='acquiring',columns=int(seen.sum()),missing_seconds=missing,phase=self.phase,
                    template=None,eta=None,jumps=self.jumps,feature_y=[float(v) if np.isfinite(v) else None for v in y],candidate_template=candidate_template,candidate_phase=candidate_phase,candidate_shape_error=candidate_error,candidate_cost_margin=candidate_margin,pending_template=self.templates[self.pending[0]].key if self.pending else None,pending_seconds=now-self.pending[1] if self.pending else None)
        if self.selected is None:return report
        t=self.templates[self.selected];report.update(template=t.key,period=t.period,phase=self.phase,accepted_shape_error=float(loss[self.selected,int(round(self.phase*len(self.grid)))%len(self.grid)]))
        matching=self.matching_settings()
        report['matching_thresholds']={k:matching[k] for k in ('minimum_columns','max_shape_error','max_predict_seconds')}
        if missing is None or missing>matching['max_predict_seconds']:report['status']='lost';return report
        elapsed=max(0,(dispatch_time if dispatch_time is not None else now)-now)
        onset=self.onset_decision(t,self.phase,elapsed)
        if onset is None:return report
        report.update(eta=onset['eta'],status='observed' if missing<.001 else 'predicting',onset_index=onset['onset_index'],onset_direction=onset['direction'],onset_phase=onset['phase'],extra_early_seconds=onset['extra_early_seconds'],dispatch_window_seconds=onset['dispatch_window_seconds'])
        if onset['due']:
            report.update(trigger=True,status='jump_due')
        return report

    def on_trigger(self,now):self.jumps+=1


class RopeProgress:
    """Count continuous crossings of template danger nodes, not repeated key pulses."""
    def __init__(self):
        self.count=0;self.previous=None;self.last_crossing=None
    @property
    def stage(self):return sum(self.count>=n for n in (0,10,30,50,70))
    def update(self,now,decision,template):
        phase=decision.get('phase')
        if template is None or phase is None or decision.get('status') not in ('observed','predicting','jump_due'):
            self.previous=None;return self.stage
        current=(now,template.key,phase)
        old=self.previous;self.previous=current
        if old is None or old[1]!=template.key:return self.stage
        dt=now-old[0];advance=(phase-old[2])%1
        # Reanchoring and template changes are not physical rope crossings.
        expected=dt/template.period
        if not 0<dt<=.3 or advance>.4 or abs(advance-expected)>.08:return self.stage
        nodes=template.data['jump_progress_nodes']
        for node in nodes:
            distance=(float(node)-old[2])%1
            if 0<distance<=advance and (self.last_crossing is None or now-self.last_crossing>=.18):
                self.count+=1;self.last_crossing=now
        return self.stage
