"""Whole-cycle image playback. Shared local image features and stage hints; no angular matching.
Its geometric phase decisions never determine this selector's playback clock.
"""
from collections import deque
from pathlib import Path
import hashlib,json,math,time
import cv2
import numpy as np
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate
from modular_agent.realtime.rope_appearance import rope_evidence
from modular_agent.realtime.jump_rope_start_gate import waiting_observation
from modular_agent.realtime.audio_cues import low_entry_authorized

class ImageCyclePlayback:
    def __init__(self,templates,grid_size=64):
        self.templates=templates;self.grid=np.arange(grid_size)/grid_size;self.history=deque();self.selected=None;self.start=None;self.stage=None;self.last=None;self.switches=0;self.pending=None;self.last_event=None;self.phase_hints={};self.low_entry_direction=None;self.low_since=None
    def select_stage(self,stage,now):
        pool=[t for t in self.templates if t.context[0]==stage]
        if not pool:return []
        if stage!=self.stage:
            old=self.selected;u=0 if self.start is None else (now-self.start)/old.period
            matching=[t for t in pool if old and t.context[1:3]==old.context[1:3]]
            self.selected=(matching or [t for t in pool if t.context[1:3]==('normal','forward')] or pool)[0]
            # Templates may use different cycle anchors. Preserve the displayed
            # shape across stage retiming, not an unrelated numeric time fraction.
            progress=u%1
            if old is not None and matching:
                x=np.linspace(.25,.8,41);old_y=old.curve(progress,x);options=[]
                for candidate in matching:
                    for p in self.grid:
                        y=candidate.curve(p,x);valid=np.isfinite(y)&np.isfinite(old_y)
                        if valid.sum()>=12:options.append((float(np.mean((y[valid]-old_y[valid])**2)),candidate,float(p)))
                if options:_,self.selected,progress=min(options,key=lambda item:item[0])
            self.start=now-progress*self.selected.period
            self.stage=stage;self.history.clear();self.pending=None;self.phase_hints={};self.last_event='stage_template_retime'
        return pool
    def update(self,now,stage,tables,scene=False,audio_hint=None):
        if self.last is not None and now<=self.last:raise ValueError('nonmonotonic cycle clock')
        self.last=now;pool=self.select_stage(stage,now)
        if not pool:return dict(path='unsupported_stage',progress=None,template=None)
        predicted=(now-self.start)/self.selected.period
        while self.history and now-self.history[0][0]>.40:self.history.popleft()
        # Scene changes invalidate old image association evidence, but not playback.
        if scene:self.history.clear();self.pending=None
        current_max=max((float(np.nanmax(v['q'])) for v in tables.values()),default=0)
        if not scene and current_max>=.28:self.history.append((now,{k:v['q'].copy() for k,v in tables.items()}))
        scores=[];previous_hints=dict(self.phase_hints)
        for t in pool:
            table=tables[t.key];now_q=table['q'];history=[];ages=[]
            for at,rows in self.history:
                if t.key in rows:
                    u=(self.grid+(at-now)/t.period)%1;history.append(np.interp(u,np.r_[self.grid,1],np.r_[rows[t.key],rows[t.key][0]]));ages.append(now-at)
            if history:
                h=np.array(history);valid=np.isfinite(h);count=valid.sum(axis=0);score=np.divide(np.where(valid,h,0).sum(axis=0),count,out=np.zeros(len(self.grid)),where=count>0)
                score*=.75+.25*count/max(1,len(history));score[count<min(3,len(history))]=0
            else:score=np.zeros(len(self.grid))
            j=int(score.argmax());u=float(self.grid[j]);gap=abs((self.grid-u+.5)%1-.5)
            if score[j]>0:self.phase_hints[t.key]=(now,u)
            score_margin=float(score[j]-np.max(score[gap>=.08]));q=float(now_q[j]) if math.isfinite(now_q[j]) else 0.;coverage=float(table['coverage'][j]);moving=float(table['moving'][j]);support=int(np.count_nonzero(table['seen'][j]))
            short=[row for age,row in zip(ages,history) if age<=.12]
            sh=np.array(short) if short else np.zeros((0,len(self.grid)));valid=np.isfinite(sh);count=valid.sum(axis=0);short_score=np.divide(np.where(valid,sh,0).sum(axis=0),count,out=np.zeros(len(self.grid)),where=count>0);short_score[count<min(3,len(short))]=0
            sj=int(short_score.argmax());su=float(self.grid[sj]);sgap=abs((self.grid-su+.5)%1-.5)
            short_fit=dict(template=t,progress=su,score=float(short_score[sj]),phase_margin=float(short_score[sj]-np.max(short_score[sgap>=.08])),q=float(now_q[sj]) if math.isfinite(now_q[sj]) else 0.,coverage=float(table['coverage'][sj]),moving=float(table['moving'][sj]),support=int(np.count_nonzero(table['seen'][sj])))
            scores.append(dict(template=t,progress=u,score=float(score[j]),phase_margin=score_margin,q=q,coverage=coverage,moving=moving,support=support,short_fit=short_fit))
        scores.sort(key=lambda s:s['score'],reverse=True)
        # Preserve known game transitions: a circle never reverses directly;
        # low swing reverses the entry direction. Retain illegal candidates as
        # diagnostics without allowing them to take over from a lucky image.
        def legal(s):
            target=s['template'].context
            if target[1]=='low_swing':return True
            if self.selected.context[1]!='low_swing':return target[2]==self.selected.context[2]
            if self.low_entry_direction is None:return True
            return target[2]!=self.low_entry_direction
        eligible=[s for s in scores if legal(s)];best=eligible[0];incumbent=next(s for s in scores if s['template'] is self.selected)
        # Mode transitions use a fresh window: old low-swing frames cannot hold
        # a newly visible upper arc for another whole history window.
        incumbent_low=self.selected.context[1]=='low_swing'
        cross=[s['short_fit'] for s in eligible if (s['template'].context[1]=='low_swing')!=incumbent_low]
        if incumbent_low and self.low_entry_direction is not None:
            expected='reverse' if self.low_entry_direction=='forward' else 'forward'
            cross=[s for s in cross if s['template'].context[2]==expected]
        if cross:
            short_best=max(cross,key=lambda s:s['score']);short_incumbent=incumbent['short_fit']
            if short_best['score']>=short_incumbent['score']+.08 and short_best['q']>=.55:
                best=short_best;incumbent=short_incumbent
        # Recent sound can break a near tie, but never overrule a visibly better fit.
        if audio_hint and 0<=now-audio_hint.get('time',-100)<=3:
            role=audio_hint.get('motion_hint');compatible=[s for s in eligible if s['template'].context[1]==role and best['score']-s['score']<=.015]
            if compatible:best=max(compatible,key=lambda s:s['score'])
        # A stale history lead must not protect a visually unsupported shape.
        # Compare only alternatives of the same stage/gear/direction here.
        if best['q']<.48:
            fresh=[s for s in eligible if s['template'].context[:3]==best['template'].context[:3] and s['q']>=.55 and s['coverage']>=.35 and best['score']-s['score']<=.035]
            if fresh:best=max(fresh,key=lambda s:s['q'])
        result=dict(path='predict_only',template=self.selected.key,progress=predicted%1,period_seconds=self.selected.period,phase_correction=0.,scores=[dict(template=s['template'].key,progress=s['progress'],score=s['score'],quality=s['q'],phase_margin=s['phase_margin']) for s in scores],trusted=False)
        static_supported=best['q']>=.70 and best['coverage']>=.55 and best['support']>=18 and len(self.history)>=4 and self.history[-1][0]-self.history[0][0]>=.12
        trusted=not scene and best['q']>=.48 and best['coverage']>=.35 and (best['moving']>=.06 or best['q']>=.65 and best['coverage']>=.50 and best['moving']>=.015 or static_supported) and best['support']>=12 and best['phase_margin']>=.015
        result.update(trusted=trusted,quality=best['q'],coverage=best['coverage'],moving=best['moving'],support=best['support'])
        if not trusted:
            # A brief occlusion pauses evidence; it does not erase a coherent run.
            if self.pending is not None and now-self.pending['time']>.12:self.pending=None
            return result
        self.phase_hints[best['template'].key]=(now,best['progress'])
        delta=(best['progress']-predicted+.5)%1-.5
        if best['template'] is self.selected and abs(delta)<=.04:
            correction=float(np.clip(delta*.25,-.008,.008));self.start-=correction*self.selected.period;self.pending=None;result.update(path='gentle',phase_correction=correction,progress=((now-self.start)/self.selected.period)%1);return result
        changed=best['template'] is not self.selected
        if changed:
            if self.selected.context[1]=='low_swing' and self.low_since is not None and now-self.low_since<self.selected.period:
                self.pending=None;result['path']='low_minimum_cycle_hold';return result
            # Role/template alternatives need sustained superiority, not one lucky frame.
            if best['score']<incumbent['score']+.012:self.pending=None;result['path']='candidate_tie_hold';return result
            if best['template'].context[1]=='low_swing' and self.selected.context[1]!='low_swing':
                authorized=audio_hint and audio_hint.get('motion_hint')=='low_swing' and 0<=now-audio_hint.get('time',-100)<=3
                if not authorized:result['path']='low_entry_needs_audio';self.pending=None;return result
        key=best['template'].key;strict_handoff=stage==2;signature=(key,) if strict_handoff or not changed else best['template'].context[:3]
        prior=previous_hints.get(key)
        own_coherent=prior is None or now-prior[0]>.12 or abs((best['progress']-prior[1]-(now-prior[0])/best['template'].period+.5)%1-.5)<=.06
        pending_coherent=self.pending is None or self.pending['key']!=key or abs((best['progress']-self.pending['clock']-(now-self.pending['time'])/best['template'].period+.5)%1-.5)<=.06
        if strict_handoff and self.pending is not None and self.pending['key']==key:
            origin=self.pending.get('origin_clock',self.pending['clock']+(self.pending['since']-self.pending['time'])/best['template'].period)
            pending_coherent=pending_coherent and abs((best['progress']-origin-(now-self.pending['since'])/best['template'].period+.5)%1-.5)<=.06
        if self.pending is None or self.pending['signature']!=signature or not own_coherent or strict_handoff and not pending_coherent:
            self.pending=dict(key=key,signature=signature,since=now,count=1,clock=best['progress'],origin_clock=best['progress'],time=now)
        else:self.pending.update(key=key,count=self.pending['count']+1,clock=best['progress'],time=now)
        needed_span=.20 if changed else .12;needed_frames=6 if changed else 4
        low_entry=changed and best['template'].context[1]=='low_swing' and self.selected.context[1]!='low_swing'
        if low_entry and best['q']>=.60 and best['score']-incumbent['score']>=.10:
            needed_span=.03;needed_frames=3
        elif changed and self.selected.context[1]=='low_swing':
            needed_span=.06;needed_frames=4
        elif changed and audio_hint and 0<=now-audio_hint.get('time',-100)<=3 and audio_hint.get('motion_hint')==best['template'].context[1] and audio_hint.get('distance',1)<=.26 and audio_hint.get('margin',0)>=.015:
            needed_span=.12;needed_frames=4
        # Different templates have different cycle origins: compare displayed
        # shapes, never subtract their unrelated numeric time fractions.
        x=np.linspace(.25,.8,41);before=self.selected.curve(predicted,x);after=best['template'].curve(best['progress'],x);common=np.isfinite(before)&np.isfinite(after)
        shape_jump=float(np.sqrt(np.mean((before[common]-after[common])**2))) if common.sum()>=12 else None
        circle_handoff=changed and self.selected.context[1]!='low_swing' and best['template'].context[1]!='low_swing'
        large_handoff=strict_handoff and circle_handoff and (shape_jump is None or shape_jump>.06)
        result.update(shape_jump_rmse=shape_jump,large_phase_handoff=large_handoff)
        if large_handoff:
            # Gear confirmation alone cannot authorize a new arc. Its own
            # phase chain and stronger visible support must establish recovery.
            needed_span=max(needed_span,.30);needed_frames=max(needed_frames,8)
            if best['q']<.65 or best['coverage']<.50 or best['support']<18:
                self.pending=None;result.update(path='phase_handoff_needs_visible_support',pending=key,pending_span=0.,pending_frames=0);return result
        result.update(path='collecting_switch' if changed else 'collecting_recovery',pending=key,pending_span=now-self.pending['since'],pending_frames=self.pending['count'])
        if self.pending['count']<needed_frames or now-self.pending['since']<needed_span:return result
        if low_entry:self.low_entry_direction=self.selected.context[2];self.low_since=now
        previous=self.selected.key;self.selected=best['template'];self.start=now-best['progress']*self.selected.period;self.switches+=int(changed);self.pending=None;self.last_event='template_switch' if changed else 'phase_recovery'
        result.update(path='switch' if changed else 'recovery',template=self.selected.key,progress=best['progress'],period_seconds=self.selected.period,phase_correction=delta,previous_template=previous)
        # Evidence from before a committed motion change must not pull us back.
        if changed:self.history.clear()
        return result

class TimedCycleVision:
    def __init__(self,root,legacy,config,module):
        self.root=Path(root);self.legacy=legacy;self.bank=legacy.bank;self.c=config;self.module=module;self.settings=config['phase_parameters']
        catalog=json.loads((self.root/self.settings['timed_catalog']).read_text(encoding='utf-8'));self.catalog_snapshot=catalog;self.templates=[]
        for entry in catalog['templates']:
            p=self.root/entry['file']
            if hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('timed catalog hash mismatch')
            self.templates.append(TimedRopeTemplate(json.loads(p.read_text(encoding='utf-8'))))
        self.atlas_data=json.loads((self.root/self.settings['atlas']).read_text(encoding='utf-8'));self.reset_playback()
    def reset_playback(self):
        self.playback=ImageCyclePlayback(self.templates,self.settings.get('timed_grid_size',64));self.features=self.module.PhaseRopeVision(self.c,self.atlas_data);self.cached_stage=None;self.lookup=None;self.last_review=None;self.previous=None;self.low=None;self.high=None;self.frame_count=0;self.weak_frames=0
    def reset(self):
        self.legacy.reset();self.bank=self.legacy.bank;self.reset_playback()
    def prepare_stage(self,stage,gray):
        if self.cached_stage!=stage:
            pool=[t for t in self.templates if t.context[0]==stage];x=np.linspace(.225,.819,41);curves=[];mask=[];lookup={};shared={}
            for t in pool:
                ids=[]
                for u in self.playback.grid:
                    y=t.curve(u,x);valid=np.isfinite(y);filled=np.interp(x,x[valid],y[valid]) if valid.sum()>=2 else np.full(41,.5)
                    signature=(np.round(filled,12).tobytes(),valid.tobytes())
                    if signature not in shared:
                        shared[signature]=len(curves);curves.append(np.column_stack([x,filled]));mask.append(valid)
                    ids.append(shared[signature])
                lookup[t.key]=np.array(ids,int)
            self.features.reference_curves=np.array(curves);self.features.grid=np.arange(len(curves));self.features.geometry=None;self.known=np.array(mask);self.lookup=lookup;self.cached_stage=stage
        self.features.prepare(gray)
        # Three normal offsets cover the same +/-4px band with bounded cost.
        l,t,r,b=self.c['roi'];pixels=(self.features.reference_curves-[l,t])*self.features.units
        self.features.offsets=np.array([-4.,0.,4.]);self.features.options=pixels[:,:,None,:]+self.features.normals[:,:,None,:]*self.features.offsets[None,None,:,None]
        h,w=gray.shape;xy=self.features.options
        self.features.in_bounds=(xy[...,0]>=0)&(xy[...,0]<w)&(xy[...,1]>=0)&(xy[...,1]<h)&self.known[:,:,None]
        self.features.body|=~self.known
    def detect(self,image,timestamp=None):
        now=time.perf_counter() if timestamp is None else timestamp
        # Only the stage badge is reused here. No old phase or speed selection runs.
        if self.legacy.stage_badge is not None:
            hint=self.legacy.stage_badge.update(image,now)
            if hint is not None:self.bank.set_stage(hint,now)
        stage=getattr(self.bank,'count_stage_index',self.bank.stage_index)+1
        if stage>=5:
            old=self.legacy.detect(image,timestamp=now)
            old['timed_playback']=dict(path='stage5_legacy_fallback',scope='stages_1_4_except_stage2_decelerate');return old
        width=self.settings['inference_width'];scale=min(1,width/image.shape[1]);small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image;gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        if self.previous is not None and self.previous.shape!=gray.shape:self.reset_playback()
        delta=np.zeros_like(gray) if self.previous is None else cv2.absdiff(gray,self.previous);scene=bool(np.mean(delta>30)>.45)
        if self.low is None or scene:self.low=gray.astype(float);self.high=self.low.copy()
        else:self.low=np.minimum(gray,self.low+2);self.high=np.maximum(gray,self.high-2)
        edges=cv2.Canny(gray,25,70);self.legacy.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8));self.legacy.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);self.legacy.variation=self.high-self.low
        self.previous=gray.copy();self.frame_count+=1
        old=waiting_observation();old['scene_changed']=scene;old['stage_source']='stage_badge_or_count';old['stage_change']=getattr(self.bank,'last_stage_change',None)
        self.prepare_stage(stage,gray)
        pool=self.playback.select_stage(stage,now)
        global_search=scene or not self.playback.phase_hints or self.frame_count%(4 if self.weak_frames>=4 else 8)==0
        if global_search:indices=np.arange(len(self.features.grid))
        else:
            chosen=[]
            for temp in pool:
                at,phase_hint=self.playback.phase_hints.get(temp.key,(now,0.))
                predicted_hint=(phase_hint+(now-at)/temp.period)%1
                local=np.flatnonzero(abs((self.playback.grid-predicted_hint+.5)%1-.5)<=.065)
                chosen.extend(self.lookup[temp.key][local])
            indices=np.unique(np.array(chosen,int))
        n=len(self.features.grid);q=np.full(n,np.nan);raw=np.zeros((n,41,2));seen=np.zeros((n,41),bool);coverage=np.zeros(n);moving=np.zeros(n)
        values=rope_evidence(self.legacy,self.features,gray,indices,small) if self.settings.get('rope_appearance_guard',False) else self.legacy._evidence(self.features,gray,indices)
        q[indices],raw[indices],seen[indices],coverage[indices],moving[indices]=values
        tables={k:dict(q=q[ids],raw=raw[ids],seen=seen[ids],coverage=coverage[ids],moving=moving[ids]) for k,ids in self.lookup.items()}
        audio_hint=getattr(self,'audio_hint_event',None) or getattr(self.bank,'speed_audio_hint',None)
        prefix=getattr(self,'audio_hint_prefix',None)
        if low_entry_authorized(prefix,now,lifetime=.40,threshold=.22,margin=.05):audio_hint=prefix
        review=self.playback.update(now,stage,tables,scene=scene,audio_hint=audio_hint);self.weak_frames=0 if review['trusted'] else self.weak_frames+1;review['global_search']=global_search;review['evaluated_curves']=len(indices);self.last_review=review;t=self.playback.selected;u=review['progress'];x=np.linspace(.225,.819,41);y=t.curve(u,x);known=np.isfinite(y);filled=np.interp(x,x[known],y[known]) if known.sum()>=2 else np.full(41,.5);curve=np.column_stack([x,filled]);nearest=int(round(u*len(self.playback.grid)))%len(self.playback.grid);table=tables[t.key];selected_q=float(table['q'][nearest]) if math.isfinite(table['q'][nearest]) else 0.;good=bool(review['trusted'] and selected_q>=.40 and review['path'] not in ('collecting_switch','low_entry_needs_audio'));observed=self.legacy._support(self.features,curve,table['raw'][nearest],table['seen'][nearest],good)&known
        # An independent appearance score is diagnostic until false-negative
        # coverage is validated; it must not silently block visible prediction.
        appearance=rope_evidence(self.legacy,self.features,gray,np.array([self.lookup[t.key][nearest]]),small)
        review['appearance_quality']=float(appearance[0][0]);review['appearance_support']=int(appearance[2][0].sum());review['appearance_guard_active']=bool(self.settings.get('rope_appearance_guard',False))
        mode='low_swing' if t.context[1]=='low_swing' else 'rotation_'+t.context[2];phase=(now-self.playback.start)/t.period;role=t.context[1];gear={'decelerate':0,'normal':1,'accelerate':2,'low_swing':0}[role]
        o=dict(old);o.update(valid=good,rope_rejection=None if good else 'no_trusted_visible_fragment',selection_method='timed_template_image_playback',motion_state=mode,motion_mode_candidate=None,tracking_status='tracking' if good else 'occluded_predicting',rope_valid=good,whole_curve=curve.tolist(),whole_point_states=['measured' if seen else 'predicted' if valid else 'unknown' for seen,valid in zip(observed,known)],whole_observed_points=((table['raw'][nearest][observed]/self.features.units)+np.array(self.c['roi'][:2])).tolist(),whole_coverage=float(observed.mean()),rope_points=[],model_exists=bool(known.sum()>=2),selected_hypothesis=t.key,template_label=f'stage_{stage}/{role}/{t.context[2]}',template_calibration=t.data['source_kind'],difficulty_stage=stage,effective_speed_stage=stage,count_stage=stage,branch_role=role,model_bank_size=len(tables),mode_changes=self.playback.switches,gear_changes=self.playback.switches,last_motion_event=self.playback.last_event,phase_visual_quality=selected_q,timed_playback=dict(review,displayed_score_evaluated=bool(np.isfinite(table['q'][nearest])),source_kind=t.data['source_kind'],period_source=t.data['period_source'],jump_progress_nodes=t.data['jump_progress_nodes'],clock_unwrapped=phase),visible_fragment_fit=dict(path=review['path'],trusted=review['trusted'],speed_applied=review['path']=='switch'),hand_anchors=[])
        o['phase_estimate']=dict(phase=u,phase_unwrapped=phase,rate=1/t.period,clock_rate=1/t.period,speed_gear=gear,speed_bounds=[1/t.period,1/t.period],template_acceleration=0.,confidence=selected_q if good else 0.,locked=True,continuation='timed_cycle_'+review['path'],coordinate='elapsed_cycle_progress',association_rejection=None)
        self.bank.time=now
        return o
