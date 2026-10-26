"""Independent C4: template clocks, bounded gear rates and boundary model bank."""
import math
import time
import json
from pathlib import Path
import numpy as np
import cv2
from modular_agent.realtime.trajectory_bank import TrajectoryBank
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank
from modular_agent.realtime.stage_badge import StageBadge
from modular_agent.realtime.coexisting_stage_bank import CoexistingStageBank
from modular_agent.realtime.evidence_recovery_bank import EvidenceRecoveryBank
from modular_agent.realtime.terminal_stage_bank import TerminalStageBank
from modular_agent.realtime.acceleration_evidence_bank import AccelerationEvidenceBank
from modular_agent.realtime.visible_rope_fit import VisibleRopeFit


# Loader supplies C3 only for its shared local image features, not its decisions.
def gear_vision_type(base):
    class PhaseGearVision(base):
        def __init__(self,config,*args):
            self.capture_roi=list(config['roi'])
            params=config['phase_parameters']
            if type(params.get('exit_clock_fit',False)) is not bool:raise ValueError('invalid exit_clock_fit')
            residual=params.get('exit_phase_fit_residual',.012)
            if type(residual) not in (int,float) or not math.isfinite(residual) or not .006<=residual<=.025:raise ValueError('invalid exit_phase_fit_residual')
            if config['phase_parameters'].get('stage_model',False) and config['phase_parameters'].get('separate_stage_roi',False):
                config=dict(config);config['roi']=[.17,.02,.88,.72]
            super().__init__(config,*args)

        def reset(self):
            super().reset()
            curves=self.rotation.atlas.curves(np.arange(2048)/2048)
            self.boundary=float(np.argmax(curves[:,20,1])/2048)
            distances=np.mean(np.linalg.norm(self.swing.reference_curves-curves[round(self.boundary*2048)],axis=2),axis=1)
            entry=float(self.swing.grid[int(np.argmin(distances))])
            self.entry_angle=math.acos(1-2*entry)/(2*math.pi)
            if type(self.settings.get("landing_branches",False)) is not bool:raise ValueError("invalid landing_branches")
            bank_type=LandingTrajectoryBank if self.settings.get("landing_branches",False) else TrajectoryBank
            self.stage_badge=None
            if type(self.settings.get("stage_model",False)) is not bool:raise ValueError("invalid stage_model")
            if self.settings.get("stage_model",False):
                folder=Path(__file__).resolve().parents[1]/'data/jump_rope_phase'
                profiles=json.loads((folder/self.settings['stage_profiles_asset']).read_text(encoding='utf-8'))
                badge=json.loads((folder/self.settings['stage_badges_asset']).read_text(encoding='utf-8'))
                self.bank=(TerminalStageBank if self.settings.get("terminal_stage_strategy",False) else AccelerationEvidenceBank if self.settings.get("acceleration_evidence_policy",False) else EvidenceRecoveryBank if self.settings.get("temporal_speed_recovery",False) else CoexistingStageBank if self.settings.get("coexisting_stage_branches",False) else StagedTrajectoryBank)(self.settings,self.boundary,self.entry_angle,profiles)
                self.stage_badge=StageBadge(badge,self.capture_roi)
            else:self.bank=bank_type(self.settings,self.boundary,self.entry_angle)
            if self.settings.get('directional_swing_exit',False):
                coordinate=self.settings.get('swing_exit_coordinate',.5)
                reference=self.swing_atlas.curves(coordinate)
                tangent=(self.swing_atlas.curves(coordinate+.001)-self.swing_atlas.curves(coordinate-.001))/.002
                grid=np.arange(2048)/2048
                curves=self.rotation.atlas.curves(grid)
                derivative=(self.rotation.atlas.curves(grid+.001)-self.rotation.atlas.curves(grid-.001))/.002
                joins={}
                for mode,direction,half in [('rotation_reverse',-1,1),('rotation_forward',1,-1)]:
                    aligned=np.sum(derivative*direction*tangent*half,axis=(1,2))>0
                    error=np.mean(np.linalg.norm(curves-reference,axis=2),axis=1)
                    joins[mode]=float(grid[int(np.argmin(np.where(aligned,error,np.inf)))])
                self.bank.c['swing_exit_rotation_join']=joins
            self.acquisition_chain=type(self.alternative_chain)(True)
            self.tables={};self.last_quality=0.;self.confirmed=False
            self.visible_fit=VisibleRopeFit()
            self.exit_chain=type(self.alternative_chain)(True)
            self.rotation_rate_chain=type(self.alternative_chain)(True)
            self.rotation_recovery_chain=type(self.alternative_chain)(True)

        def evidence_table(self,vision,gray,indices):
            indices=np.unique(indices).astype(int)
            q,raw,seen,coverage,moving=self._evidence(vision,gray,indices)
            return dict(indices=indices,q=q,raw=raw,seen=seen,coverage=coverage,moving=moving)

        def detect(self,image,timestamp=None):
            now=time.perf_counter() if timestamp is None else timestamp
            captured_image=image
            if self.stage_badge is not None and self.settings.get('separate_stage_roi',False):
                l,t,r,b=self.capture_roi;x1,y1,x2,y2=self.c['roi'];h,w=image.shape[:2]
                image=image[round((y1-t)/(b-t)*h):round((y2-t)/(b-t)*h),round((x1-l)/(r-l)*w):round((x2-l)/(r-l)*w)]
            width=self.settings['inference_width'];scale=min(1,width/image.shape[1])
            small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image
            gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            if self.previous is not None and self.previous.shape!=gray.shape:self.reset()
            if self.stage_badge is not None:
                stage=self.stage_badge.update(captured_image,now)
                if stage is not None:self.bank.set_stage(stage,now)
            delta=np.zeros_like(gray) if self.previous is None else cv2.absdiff(gray,self.previous)
            scene=bool(np.mean(delta>30)>.45)
            if self.low is None or scene:self.low=gray.astype(float);self.high=self.low.copy()
            else:self.low=np.minimum(gray,self.low+2);self.high=np.maximum(gray,self.high-2)
            edges=cv2.Canny(gray,25,70);self.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
            moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
            self.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);self.variation=self.high-self.low
            self.rotation.prepare(gray);self.swing.prepare(gray);self.frame_count+=1
            if not self.bank.items:
                self.bank.acquire(0.,now);self.bank.locked=False
                dt=0.
            else:dt=self.bank.advance(now)
            active_before=next(p for p in self.bank.items if p.key==self.bank.active)
            global_search=not self.confirmed or self.bank.weak_seconds>.15 and (self.frame_count%10==0 or self.settings.get('observed_speed_recovery',False))
            priority_tables={}
            for vision,mode in ((self.rotation,'rotation'),(self.swing,'low_swing')):
                if global_search and mode=='rotation':indices=np.arange(len(vision.grid))
                else:
                    selected=[]
                    for p in self.bank.items:
                        if (p.mode=='low_swing')!=(mode=='low_swing'):continue
                        gap=vision.grid-p.coordinate
                        if mode=='rotation':gap=(gap+.5)%1-.5
                        selected.extend(np.flatnonzero(abs(gap)<(.12 if mode=='low_swing' else .045)))
                    if active_before.mode=='low_swing' and mode=='rotation':selected.extend(np.flatnonzero(vision.reference_curves[:,20,1]<.33))
                    indices=np.array(selected,dtype=int)
                if self.settings.get('visible_fragment_priority',False):
                    full=self.evidence_table(vision,gray,np.arange(len(vision.grid)));priority_tables[mode]=full
                    local_indices=np.unique(indices).astype(int)
                    self.tables[mode]={k:v[local_indices] for k,v in full.items()} if len(local_indices) else None
                else:self.tables[mode]=self.evidence_table(vision,gray,indices) if len(indices) else None
            table=self.tables['rotation']
            if not self.confirmed and table is not None:
                eligible=np.where((table['moving']>.08)&(table['coverage']>.30),table['q'],0.)
                best=int(np.argmax(eligible));phase=float(self.rotation.grid[table['indices'][best]])
                if self.acquisition_chain.update(phase,float(eligible[best]) if not scene else 0.,now):
                    slope=self.acquisition_chain.slope()
                    if slope is not None and abs(slope)>.12:
                        self.bank.acquire(phase,now,1 if slope>0 else -1);self.confirmed=True;dt=0.
                        # Initial direction comes from the short image chain;
                        # noisy few-frame slopes do not overwrite calibrated rates.
            # An upper arc cannot belong to the low-only trajectory. Accumulate
            # an independent coherent phase chain to recover an occluded exit.
            if active_before.mode=='low_swing' and table is not None and self.bank.low_played_cycles>=1.:
                phases=self.rotation.grid[table['indices']]
                good=(self.rotation.reference_curves[table['indices'],20,1]<.33)&(table['q']>=.55)&(table['moving']>=.10)&(table['coverage']>=.35)
                scores=np.where(good,table['q'],0.);j=int(np.argmax(scores))
                self.exit_chain.update(float(phases[j]),float(scores[j]) if not scene else 0.,now)
                records=self.exit_chain.records
                if len(records)>=5 and now-records[0][0]>=.12 and records[-1][0]==now:
                    expected=-self.bank.low_entry_direction;slope=self.exit_chain.slope()
                    ts=np.array([r[0] for r in records]);xs=np.array([r[1] for r in records]);ts-=ts[-1]
                    clock_fit=self.settings.get('exit_clock_fit',False)
                    if clock_fit:
                        mode='rotation_forward' if expected>0 else 'rotation_reverse'
                        xs=np.unwrap(np.array([self.bank.rotation_clock(mode,x)%1 for x in xs])*2*np.pi)/(2*np.pi)
                        slope=float(np.polyfit(ts,xs,1)[0])
                    fit=np.polyfit(ts,xs,1);residual=float(np.sqrt(np.mean((xs-np.polyval(fit,ts))**2)))
                    if slope is not None and slope*expected>.3 and (xs[-1]-xs[0])*expected>.06 and residual<self.settings.get('exit_phase_fit_residual',.012):
                        self.bank.reconstruct_exit(float(phases[j]),abs(slope),now,clock_rate=clock_fit)
            else:self.exit_chain=type(self.alternative_chain)(True)
            if self.settings.get('rotation_rate_assist',False) and not self.bank.rotation_rearmed and active_before.mode!='low_swing' and table is not None:
                phases=self.rotation.grid[table['indices']]
                good=(self.rotation.reference_curves[table['indices'],20,1]<.33)&(table['q']>=.55)&(table['moving']>=.10)&(table['coverage']>=.35)
                scores=np.where(good,table['q'],0.);j=int(np.argmax(scores))
                self.rotation_rate_chain.update(float(phases[j]),float(scores[j]) if not scene else 0.,now)
                records=self.rotation_rate_chain.records
                if len(records)>=5 and now-records[0][0]>=.12 and records[-1][0]==now:
                    ts=np.array([r[0] for r in records]);xs=np.array([r[1] for r in records]);ts-=ts[-1]
                    fit=np.polyfit(ts,xs,1);residual=float(np.sqrt(np.mean((xs-np.polyval(fit,ts))**2)))
                    if fit[0]*active_before.direction>.3 and residual<.012:
                        self.bank.rate_hint=dict(rate=abs(float(fit[0])),time=now);self.bank.rate_hint_mode=active_before.mode
            if self.settings.get('observed_speed_recovery',False) and self.confirmed and active_before.mode!='low_swing' and table is not None:
                phases=self.rotation.grid[table['indices']]
                good=(self.rotation.reference_curves[table['indices'],20,1]<.33)&(table['q']>=self.settings.get('recovery_quality_min',.70))&(table['moving']>=self.settings.get('recovery_motion_min',.15))&(table['coverage']>=self.settings.get('recovery_coverage_min',.50))
                scores=np.where(good,table['q'],0.);j=int(np.argmax(scores))
                self.rotation_recovery_chain.update(float(phases[j]),float(scores[j]) if not scene else 0.,now)
                records=self.rotation_recovery_chain.records
                if len(records)>=5 and now-records[0][0]>=.12 and records[-1][0]==now:
                    ts=np.array([r[0] for r in records]);ts-=ts[-1]
                    xs=np.unwrap(np.array([self.bank.rotation_clock(active_before.mode,r[1])%1 for r in records])*2*np.pi)/(2*np.pi)
                    fit=np.polyfit(ts,xs,1);residual=float(np.sqrt(np.mean((xs-np.polyval(fit,ts))**2)))
                    gap=abs((self.bank.rotation_clock(active_before.mode,float(phases[j]))-active_before.phase+.5)%1-.5)
                    gears=self.bank.gears(active_before.mode);tol=self.bank.c['gear_tolerance']
                    if gap>.06 and residual<.018 and gears[0]*(1-tol)<=fit[0]*active_before.direction<=gears[-1]*(1+tol) and abs(xs[-1]-xs[0])>.06:
                        self.bank.recover_rotation(float(phases[j]),now)
            else:self.rotation_recovery_chain=type(self.alternative_chain)(True)
            priority_fits={}
            if self.settings.get('visible_fragment_priority',False) and self.confirmed:
                for name,source in [('rotation',self.rotation),('low_swing',self.swing)]:
                    priority_fits[name]=VisibleRopeFit.select(source,priority_tables[name],self._support,scene,cyclic=name!='low_swing')
            observations={}
            for p in self.bank.items:
                mode='low_swing' if p.mode=='low_swing' else 'rotation';vision=self.swing if mode=='low_swing' else self.rotation
                table=self.tables[mode];quality=0.;moving=0.;phase_error=0.;record=None
                if table is not None:
                    coords=vision.grid[table['indices']];gap=coords-p.coordinate
                    if mode=='rotation':gap=(gap+.5)%1-.5
                    scores=table['q']-.10*np.minimum(9,(gap/.03)**2)
                    j=int(np.argmax(scores));quality=float(table['q'][j]);moving=float(table['moving'][j])
                    if abs(gap[j])<(.12 if mode=='low_swing' else .045) and not scene:
                        selected=float(coords[j])
                        if mode=='low_swing':
                            angle=math.acos(1-2*selected)/(2*math.pi)
                            if p.coordinate_velocity<0:angle=1-angle
                            angle=self.bank.warp.inverse(angle)
                            phase_error=(angle-p.phase+.5)%1-.5
                        else:phase_error=(self.bank.rotation_clock(p.mode,selected,p.gear)-p.phase+.5)%1-.5 if p.mode!='low_swing' and (p.warp is not None) else float(gap[j])
                        curve=self.swing_atlas.curves(p.coordinate) if mode=='low_swing' else self.rotation.atlas.curves(p.coordinate)
                        support=self._support(vision,curve,table['raw'][j],table['seen'][j],True)
                        p.turn_supported=bool(np.count_nonzero(support)>=8 and quality>=.45)
                        p.upper_supported=bool(mode=='rotation' and curve[20,1]<.33 and np.count_nonzero(support)>=8 and quality>=.45 and moving>=.08)
                        p.exit_supported=bool(mode=='rotation' and np.count_nonzero(support)>=12 and quality>=.55 and moving>=.10)
                        p.visual=bool(quality>=.4 and np.count_nonzero(table['seen'][j])>=12 and (moving>=.03 or mode=='low_swing' and min(p.coordinate,1-p.coordinate)<.04))
                        record=(vision,table,j,support,quality,moving)
                target=max(.05,quality-.08*(float(gap[j])/.025)**2) if p.visual else .05
                alpha=1-math.exp(-max(dt,.016)/.12)
                p.score=(1-alpha)*p.score+alpha*target
                if hasattr(self.bank,"record_evidence"):self.bank.record_evidence(p,target,quality,moving)
                priority=priority_fits.get(mode)
                if p.key!=self.bank.active or not priority or not priority['trusted']:
                    self.bank.correct(p,phase_error,dt,quality,moving)
                observations[p.key]=record
            active=self.bank.choose(now,dt);mode=active.mode
            vision=self.swing if mode=='low_swing' else self.rotation;atlas=self.swing_atlas if mode=='low_swing' else self.rotation.atlas
            visible_applied=False
            if self.settings.get('visible_fragment_priority',False) and self.confirmed:
                table=priority_tables['low_swing' if mode=='low_swing' else 'rotation']
                fitted=priority_fits.get('low_swing' if mode=='low_swing' else 'rotation')
                visible_applied=self.visible_fit.update(self.bank,active,fitted,now,dt)
            curve=atlas.curves(active.coordinate);record=observations.get(active.key)
            if visible_applied:
                j=fitted['index'];record=(vision,table,j,fitted['support'],fitted['quality'],fitted['moving'])
            support=np.zeros(41,dtype=bool);quality=0.;moving=0.;candidate=None
            if record is not None:
                _,table,j,_,quality,moving=record
                support=self._support(vision,curve,table['raw'][j],table['seen'][j],active.visual)
                candidate=float(vision.grid[table['indices'][j]])
                l,t,_,_=self.c['roi'];visible=table['raw'][j][support]/vision.units+[l,t]
            else:visible=np.empty((0,2))
            valid=bool(self.confirmed and np.count_nonzero(support)>=8 and active.visual)
            direction=active.direction if mode!='low_swing' else (1 if active.coordinate_velocity>=0 else -1)
            coordinate_rate=active.coordinate_velocity
            confidence=float(np.clip(active.score,0,1))*math.exp(-self.bank.weak_seconds/.8)
            estimate=dict(phase=active.coordinate,phase_unwrapped=active.phase,rate=coordinate_rate,clock_rate=active.speed,
                template_acceleration=active.template_acceleration,acceleration_source="constant_rate_template",speed_gear=active.gear,speed_bounds=list(self.bank.bounds(active)),confidence=confidence,
                uncertainty=min(.5,.012+self.bank.weak_seconds*.15),observed=valid,locked=self.confirmed,
                direction=direction,reversals=self.bank.direction_changes,reversal_pending=0,search_wide=global_search,
                continuation=('trusted_visible_gentle_correction' if self.visible_fit.review.get('path')=='gentle' else 'trusted_visible_recovery') if visible_applied else 'visual_clock_correction' if valid else 'candidate_clock_correction' if active.visual else 'template_playback',status='tracking' if valid else 'coasting',
                coordinate='bounded_swing' if mode=='low_swing' else 'cyclic_rotation',angular_rate=2*math.pi*active.speed if mode=='low_swing' else None)
            self.previous=gray
            return dict(valid=False,avatar_valid=False,avatar_y=None,rope_valid=valid,rope_y=float(curve[20,1]) if valid else None,
                rope_points=[],whole_curve=curve.tolist(),whole_point_states=['measured' if x else 'predicted' if confidence>.25 else 'unknown' for x in support],whole_observed_points=visible.tolist(),
                whole_coverage=float(np.mean(support[2:-2])),phase_candidate_coverage=float(np.mean(support)),hand_anchors=[],model_exists=True,
                tracking_status=estimate['status'],track_id=1 if self.confirmed else 0,phase_estimate=estimate,
                visible_fragment_fit=self.visible_fit.review,phase_visual_quality=quality,phase_visual_candidate=candidate,phase_candidates_evaluated=sum(len(t['indices']) for t in self.tables.values() if t is not None),
                phase_alternatives=[dict(key=p.key,parent=p.parent,born=p.born,mode=p.mode,role=self.bank.role(p) if self.stage_badge is not None else None,stage=(self.bank.item_stage(p) if hasattr(self.bank,"item_stage") else self.bank.stage_index)+1 if self.stage_badge is not None else None,calibration=self.bank.profile_status(p) if self.stage_badge is not None else None,gear=p.gear,clock=p.phase,coordinate=p.coordinate,velocity=p.coordinate_velocity,clock_rate=p.speed,visual=p.visual,score=p.score,window_advantage=self.bank.branch_advantage(active,p) if hasattr(self.bank,'branch_advantage') else None,legal=self.bank.legal_successor(active,p,now) if p.key!=active.key else True,landing=getattr(self.bank,'branch_info',{}).get(p.key),evidence_frames=sum(1 for r in getattr(self.bank,'evidence',{}).get(p.key,()) if r[2])) for p in sorted(self.bank.items,key=lambda p:p.score,reverse=True)[:self.settings.get('max_hypotheses',24) if self.settings.get('all_branch_diagnostics',False) else 4]],
                phase_atlas=atlas.name,phase_supported_mode='trajectory_gear_bank',motion_state=mode,mode_changes=self.bank.mode_switches,
                confirmation_pending_seconds=now-self.bank.pending_since if self.bank.pending_since is not None else 0.,confirmation_required_seconds=self.bank.c['confirmation_seconds'],active_confirmed=self.confirmed,prediction_only=not valid,mode_candidate=self.bank.pending,entering_rotation_direction=self.bank.low_entry_direction if self.bank.low_entry_direction is not None else active.direction,exit_direction_prior=-self.bank.low_entry_direction if self.bank.low_entry_direction is not None else None,
                reacquisitions=0,last_motion_event=self.bank.event,phase_candidate_moving=moving,
                motion_speed=None,motion_phase='template_clock',motion_mode_candidate=mode,scene_changed=scene,
                terminal_stage_policy=dict(requested=getattr(self.bank,'terminal_requested',False),locked=getattr(self.bank,'terminal_locked',False),started_at=getattr(self.bank,'terminal_started_at',None),review=getattr(self.bank,'terminal_review',None)),selection_method='trajectory_gear_v4',rope_rejection=None if valid else 'model_not_visually_supported',terminal=None,mode_hint=None,
                swing_pass=('back_to_front' if active.coordinate_velocity>1e-8 else 'front_to_back' if active.coordinate_velocity< -1e-8 else 'turn') if mode=='low_swing' else None,exit_half_allowed=self.bank.exit_half_allowed(active) if mode=='low_swing' else None,exit_boundary=self.bank.swing_exit_boundary(active) if mode=='low_swing' and self.settings.get('directional_swing_exit',False) else None,exit_rotation_join=self.bank.c.get('swing_exit_rotation_join'),last_exit_recovered=self.bank.last_exit_recovered,estimated_transition_time=self.bank.estimated_transition_time,low_swing_episode=self.bank.low_episode,low_entry_direction=self.bank.low_entry_direction,low_turns_observed=sorted(self.bank.low_turns),low_played_cycles=self.bank.low_played_cycles,rotation_rearmed=self.bank.rotation_rearmed,rearm_visible_travel=self.bank.rearm_travel,rearm_played_cycles=self.bank.rearm_played_cycles,rearm_upper_travel=self.bank.rearm_upper_travel,model_selection_count=self.bank.switches,selected_hypothesis=active.key,gear_changes=self.bank.gear_switches,model_bank_size=len(self.bank.items),transition_boundary=self.boundary,count_stage=(getattr(self.bank,'count_stage_index',self.bank.stage_index)+1) if self.stage_badge is not None else None,effective_speed_stage=(self.bank.stage_index+1) if self.stage_badge is not None else None,difficulty_stage=self.bank.stage_index+1 if self.stage_badge is not None else None,stage_source='badge_histogram' if self.stage_badge is not None else None,stage_confidence=self.stage_badge.confidence if self.stage_badge is not None else None,stage_change=getattr(self.bank,'last_stage_change',None),branch_role=self.bank.role(active) if self.stage_badge is not None else None,template_label=('stage_'+str(self.bank.stage_index+1)+'/'+self.bank.role(active)) if self.stage_badge is not None else None,template_calibration=self.bank.profile_status(active) if self.stage_badge is not None else None,landing_branch_adoptions=getattr(self.bank,"branch_adoptions",0),last_landing_branch=getattr(self.bank,"last_branch_adoption",None),landing_number=getattr(self.bank,"landing_number",0),speed_calibration_verified=False)
    return PhaseGearVision
