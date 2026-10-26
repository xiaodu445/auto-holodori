"""Independent C4: template clocks, bounded gear rates and boundary model bank."""
import math
import time
import numpy as np
import cv2
from modular_agent.realtime.trajectory_bank import TrajectoryBank
from modular_agent.realtime.phase_evidence import ClockRateEvidence
from modular_agent.realtime.endpoint_trajectory_bank import EndpointTrajectoryBank
from modular_agent.realtime.curve_evidence import coherent_offsets
from modular_agent.realtime.phase_evidence import PhaseEvidenceChain


# Loader supplies C3 only for its shared local image features, not its decisions.
def gear_vision_type(base):
    class PhaseGearVision(base):
        def reset(self):
            for flag in ('coherent_evidence','independent_phase_chain','independent_exit_chain'):
                if type(self.settings.get(flag,False)) is not bool:raise ValueError('invalid '+flag)
            for name,default,lower,upper in [('rope_ridge_min',8,4,64),('rope_ridge_target',10,4,64),('ridge_blend',0,0,1),('offset_continuity_penalty',.45,0,2)]:
                value=self.settings.get(name,default)
                if type(value) not in (int,float) or not math.isfinite(value) or not lower<=value<=upper:raise ValueError('invalid '+name)
            if self.settings.get('rope_ridge_target',10)<self.settings.get('rope_ridge_min',8):raise ValueError('ridge target below minimum')
            super().reset()
            curves=self.rotation.atlas.curves(np.arange(2048)/2048)
            self.boundary=float(np.argmax(curves[:,20,1])/2048)
            distances=np.mean(np.linalg.norm(self.swing.reference_curves-curves[round(self.boundary*2048)],axis=2),axis=1)
            entry=float(self.swing.grid[int(np.argmin(distances))])
            self.entry_angle=math.acos(1-2*entry)/(2*math.pi)
            self.bank=EndpointTrajectoryBank(self.settings,self.rotation.atlas,self.swing_atlas) if self.settings.get('endpoint_transitions',False) else TrajectoryBank(self.settings,self.boundary,self.entry_angle)
            self.acquisition_chain=type(self.alternative_chain)(True)
            self.tables={};self.last_quality=0.;self.confirmed=False
            self.clock_rate_chain=None;self.clock_rate_identity=None;self.clock_rate_proof=None
            self.exit_chain=type(self.alternative_chain)(True)
            self.phase_chain=PhaseEvidenceChain(min(self.settings['rotation_gears'])*(1-self.settings['gear_tolerance']),max(self.settings['rotation_gears'])*(1+self.settings['gear_tolerance']))
            self.phase_proof=None;self.phase_proof_time=None;self.phase_proof_epoch=None
            self.exit_beam=PhaseEvidenceChain(min(self.settings['rotation_gears'])*(1-self.settings['gear_tolerance']),max(self.settings['rotation_gears'])*(1+self.settings['gear_tolerance']))
            self.exit_beam_proof=None;self.edge_history=[]

        def evidence_table(self,vision,gray,indices):
            indices=np.unique(indices).astype(int)
            q,raw,seen,coverage,moving=self._evidence(vision,gray,indices)
            if vision is self.rotation:
                q=np.where(moving>=coverage*self.settings.get('moving_support_ratio',0),q,0.)
            return dict(indices=indices,q=q,raw=raw,seen=seen,coverage=coverage,moving=moving)

        def _evidence(self,vision,gray,indices):
            coherent=self.settings.get('coherent_evidence',False)
            if not coherent and (self.settings.get('rope_ridge_min',8)==8 or vision is self.swing or getattr(self,'evidence_active_mode',None)=='low_swing' and not self.settings.get('strong_rotation_while_low',False)):return super()._evidence(vision,gray,indices)
            options=vision.options[indices];normals=vision.normals[indices];inside=vision.in_bounds[indices];body=vision.body[indices]
            center=vision.sample(gray,options);bright=np.zeros(center.shape);dark=np.zeros(center.shape)
            for radius in (3,6,10):
                plus=vision.sample(gray,options+normals[:,:,None,:]*radius)
                minus=vision.sample(gray,options-normals[:,:,None,:]*radius)
                a=center-plus;b=center-minus
                bright=np.maximum(bright,np.minimum(np.maximum(a,0),np.maximum(b,0)))
                dark=np.maximum(dark,np.minimum(np.maximum(-a,0),np.maximum(-b,0)))
            edge=vision.sample(self.distance,options);motion=vision.sample(self.motion_distance,options)
            ii=np.arange(len(indices))[:,None];jj=np.arange(41)[None,:];results=[]
            regimes=[(ridge,self.settings.get('rope_ridge_min',8),self.settings.get('rope_ridge_target',10)) for ridge in ((bright,dark) if coherent else (np.maximum(bright,dark),))]
            blend=float(self.settings.get('ridge_blend',0))
            if not coherent and blend:regimes.append((np.maximum(bright,dark),8,10))
            for ridge,minimum,target in regimes:
                cost=edge+np.minimum(motion,12)*.20+np.maximum(0,target-ridge)*.50+abs(vision.offsets)[None,None,:]*.1
                if coherent:cost[body]=0.
                cost[~inside]=1e4
                best=coherent_offsets(cost,vision.offsets,self.settings.get('offset_continuity_penalty',.45)) if coherent else np.argmin(cost,axis=2)
                points=options[ii,jj,best]
                seen=(edge[ii,jj,best]<=4)&(ridge[ii,jj,best]>=minimum)&(vision.sample(self.variation,points)>=8)&(~body)&inside[ii,jj,best]
                seen[:,[0,1,-2,-1]]=False
                moving=seen&(motion[ii,jj,best]<=5)
                coverage=np.mean(seen[:,2:-2],axis=1);fraction=np.mean(moving[:,2:-2],axis=1)
                spans=np.array([np.ptp(np.flatnonzero(row))/40 if np.count_nonzero(row)>=8 else 0 for row in seen])
                quality=np.clip(coverage*.65+spans*.18+fraction*.20-.008*np.mean(np.minimum(edge[ii,jj,best],12),axis=1),0,1)
                quality[(seen.sum(axis=1)<8)|(spans<.40)]=0
                results.append((quality,points,seen,coverage,fraction))
            if not coherent and blend:
                baseline=results[1];strong=results[0]
                return ((1-blend)*baseline[0]+blend*strong[0],*baseline[1:])
            if len(results)==1:return results[0]
            choose=results[1][0]>results[0][0]
            return tuple(np.where(choose.reshape((-1,)+(1,)*(a.ndim-1)),b,a) for a,b in zip(*results))

        def detect(self,image,timestamp=None):
            now=time.perf_counter() if timestamp is None else timestamp
            width=self.settings['inference_width'];scale=min(1,width/image.shape[1])
            small=cv2.resize(image,(round(image.shape[1]*scale),round(image.shape[0]*scale))) if scale<1 else image
            gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            if self.previous is not None and self.previous.shape!=gray.shape:self.reset()
            delta=np.zeros_like(gray) if self.previous is None else cv2.absdiff(gray,self.previous)
            scene=bool(np.mean(delta>30)>.45)
            if self.low is None or scene:self.low=gray.astype(float);self.high=self.low.copy()
            else:self.low=np.minimum(gray,self.low+2);self.high=np.maximum(gray,self.high-2)
            edges=cv2.Canny(gray,25,70);self.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
            edge_age=float(self.settings.get('edge_motion_history',0))
            if edge_age>0:
                if scene:self.edge_history=[]
                prior=min(self.edge_history,key=lambda r:abs(r[0]-(now-edge_age)))[1] if self.edge_history else None
                moving_edges=np.zeros_like(edges) if prior is None else edges&np.uint8(prior>self.settings.get('edge_motion_distance',1.5))*255
                self.edge_history.append((now,self.distance.copy()));self.edge_history=[r for r in self.edge_history if now-r[0]<=.15]
            else:moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
            self.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);self.variation=self.high-self.low
            if scene:
                self.phase_chain.beams=[];self.phase_proof=None;self.phase_proof_time=None;self.exit_beam.beams=[];self.exit_beam_proof=None
            self.rotation.prepare(gray);self.swing.prepare(gray);self.frame_count+=1
            if not self.bank.items:
                self.bank.acquire(0.,now);self.bank.locked=False
                dt=0.
            else:dt=self.bank.advance(now)
            active_before=next(p for p in self.bank.items if p.key==self.bank.active)
            self.evidence_active_mode=active_before.mode
            association_radius=min(self.settings.get('recover_search_radius',.045),.045+self.bank.weak_seconds*.20)
            phase_penalty=self.settings.get('recover_phase_penalty',.1) if self.bank.weak_seconds>.15 else .1
            chain_search=bool(self.settings.get('independent_phase_chain',False) and active_before.mode!='low_swing' and self.frame_count%4==0)
            global_search=chain_search or not self.confirmed or self.bank.weak_seconds>.15 and self.frame_count%10==0
            for vision,mode in ((self.rotation,'rotation'),(self.swing,'low_swing')):
                if global_search and mode=='rotation':indices=np.arange(len(vision.grid))
                else:
                    selected=[]
                    for p in self.bank.items:
                        if (p.mode=='low_swing')!=(mode=='low_swing'):continue
                        gap=vision.grid-p.coordinate
                        if mode=='rotation':gap=(gap+.5)%1-.5
                        selected.extend(np.flatnonzero(abs(gap)<(.12 if mode=='low_swing' else association_radius)))
                    if active_before.mode=='low_swing' and mode=='rotation':selected.extend(np.flatnonzero(vision.reference_curves[:,20,1]<.33))
                    indices=np.array(selected,dtype=int)
                self.tables[mode]=self.evidence_table(vision,gray,indices) if len(indices) else None
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
                if self.settings.get('independent_exit_chain',False):
                    candidates=[]
                    for index in np.argsort(scores)[::-1]:
                        phase=float(phases[index])
                        if all(abs((phase-p+.5)%1-.5)>.035 for p,_ in candidates):candidates.append((phase,float(scores[index])))
                        if len(candidates)==6:break
                    proof=self.exit_beam.update(candidates,now,-self.bank.low_entry_direction)
                    self.exit_beam_proof=proof
                    if proof is not None and proof['quality']>=.65 and proof['error']<=.012 and proof['span']>=.16 and not scene:
                        self.bank.reconstruct_exit(proof['phase'],proof['rate'],now)
                records=self.exit_chain.records
                if len(records)>=5 and now-records[0][0]>=.12 and records[-1][0]==now:
                    expected=-self.bank.low_entry_direction;slope=self.exit_chain.slope()
                    ts=np.array([r[0] for r in records]);xs=np.array([r[1] for r in records]);ts-=ts[-1]
                    fit=np.polyfit(ts,xs,1);residual=float(np.sqrt(np.mean((xs-np.polyval(fit,ts))**2)))
                    if slope is not None and slope*expected>.3 and (xs[-1]-xs[0])*expected>.06 and residual<.012:
                        self.bank.reconstruct_exit(float(phases[j]),abs(slope),now)
            else:
                self.exit_chain=type(self.alternative_chain)(True);self.exit_beam.beams=[];self.exit_beam_proof=None
            if chain_search and table is not None and self.confirmed:
                candidates=[]
                scores=np.where((table['moving']>=.08)&(table['coverage']>=.30),table['q'],0.)
                for j in np.argsort(scores)[::-1]:
                    phase=float(self.rotation.grid[table['indices'][j]])
                    if all(abs((phase-p+.5)%1-.5)>.035 for p,_ in candidates):candidates.append((phase,float(scores[j])))
                    if len(candidates)==6:break
                if self.phase_proof_epoch!=self.bank.epoch:
                    self.phase_chain.beams=[];self.phase_proof=None
                proof=self.phase_chain.update(candidates,now,active_before.direction)
                self.phase_proof_epoch=self.bank.epoch
                if proof is not None and proof['quality']>=.65 and proof['error']<=.012 and proof['span']>=.22 and not scene:
                    self.phase_proof=proof;self.phase_proof_time=now
            if active_before.mode=='low_swing' or self.phase_proof_epoch!=self.bank.epoch:self.phase_proof=None
            chain_corrected=set()
            if self.settings.get('gear_rate_evidence',False) and self.clock_rate_identity!=(self.bank.epoch,active_before.key):
                gears=self.bank.gears(active_before.mode);tolerance=self.settings.get('swing_gear_tolerance',self.settings['gear_tolerance']) if active_before.mode=='low_swing' else self.settings['gear_tolerance']
                self.clock_rate_chain=ClockRateEvidence(min(gears)*(1-tolerance),max(gears)*(1+tolerance),max_gap=.65 if active_before.mode=='low_swing' else .25)
                self.clock_rate_identity=(self.bank.epoch,active_before.key);self.clock_rate_proof=None;self.bank.rate_hint=None;self.bank.rate_hint_mode=None
            observations={}
            for p in self.bank.items:
                mode='low_swing' if p.mode=='low_swing' else 'rotation';vision=self.swing if mode=='low_swing' else self.rotation
                table=self.tables[mode];quality=0.;moving=0.;phase_error=0.;record=None
                if table is not None:
                    coords=vision.grid[table['indices']];gap=coords-p.coordinate
                    if mode=='rotation':gap=(gap+.5)%1-.5
                    scores=table['q']-phase_penalty*np.minimum(9,(gap/(.05 if self.bank.weak_seconds>.15 and self.settings.get('recover_search_radius',.045)>.045 else .03))**2)
                    j=int(np.argmax(scores));quality=float(table['q'][j]);moving=float(table['moving'][j])
                    if abs(gap[j])<(.12 if mode=='low_swing' else association_radius) and not scene:
                        selected=float(coords[j])
                        if mode=='low_swing':
                            angle=math.acos(1-2*selected)/(2*math.pi)
                            if p.coordinate_velocity<0:angle=1-angle
                            angle=self.bank.warp.inverse(angle)
                            phase_error=(angle-p.phase+.5)%1-.5
                        else:phase_error=float(gap[j])
                        curve=self.swing_atlas.curves(p.coordinate) if mode=='low_swing' else self.rotation.atlas.curves(p.coordinate)
                        support=self._support(vision,curve,table['raw'][j],table['seen'][j],True)
                        p.turn_supported=bool(np.count_nonzero(support)>=8 and quality>=.45)
                        p.upper_supported=bool(mode=='rotation' and curve[20,1]<.33 and np.count_nonzero(support)>=8 and quality>=.45 and moving>=.08)
                        p.exit_supported=bool(mode=='rotation' and np.count_nonzero(support)>=12 and quality>=.55 and moving>=.10)
                        p.visual=bool(quality>=.4 and np.count_nonzero(table['seen'][j])>=12 and (moving>=.03 or mode=='low_swing' and min(p.coordinate,1-p.coordinate)<.04))
                        record=(vision,table,j,support,quality,moving)
                if self.settings.get('gear_rate_evidence',False) and p.key==self.bank.active and record is not None and p.visual and quality>=.5 and moving>=.08 and moving>=float(table['coverage'][j])*.35 and np.count_nonzero(support)>=8 and not scene:
                    derivative=abs(p.coordinate_velocity/p.speed)
                    if mode=='rotation' or derivative>=.5:
                        proof=self.clock_rate_chain.update(p.phase+phase_error,now,1 if mode=='low_swing' else p.direction)
                        if proof is not None:
                            self.clock_rate_proof=proof;self.bank.rate_hint=proof;self.bank.rate_hint_mode=p.mode
                innovation_penalty=0.
                if p.visual and moving>=.03 and dt>0:
                    derivative=abs(p.coordinate_velocity/p.speed)
                    resolution=.5/(len(vision.grid)-1 if mode=='low_swing' else len(vision.grid))
                    clock_noise=resolution/max(.1,derivative)
                    innovation=max(0.,abs(phase_error)-clock_noise)/max(1e-6,p.speed*dt)
                    innovation_penalty=self.settings.get('correction_energy_penalty',0)*min(1.,innovation)
                target=max(.05,quality-.08*(float(gap[j])/.025)**2-innovation_penalty) if p.visual else .05
                hint=self.bank.rate_hint
                if hint is not None and self.bank.rate_hint_mode==p.mode and now-hint['time']<=.3:
                    target+=self.settings.get('rate_evidence_bonus',0)*math.exp(-((p.speed-hint['rate'])/.06)**2)
                alpha=1-math.exp(-max(dt,.016)/.12)
                p.score=(1-alpha)*p.score+alpha*target
                proof=self.phase_proof
                proof_current=proof is not None and self.phase_proof_time is not None and now-self.phase_proof_time<=.09 and p.mode==active_before.mode and p.mode!='low_swing'
                if proof_current:
                    target_phase=(proof['phase']+p.direction*proof['rate']*(now-self.phase_proof_time))%1
                    error=(target_phase-p.phase+.5)%1-.5
                    if abs(error)<.18:
                        limit=min(self.settings['max_phase_correction'],p.speed*dt*self.settings['phase_correction_fraction'])
                        p.phase+=float(np.clip(error*.25,-limit,limit));chain_corrected.add(p.key)
                        lo,hi=self.bank.bounds(p)
                        if lo<=proof['rate']<=hi:p.speed+=float(np.clip((proof['rate']-p.speed)*.10,-.005,.005))
                        p.score=.5*p.score+.5*max(.05,proof['quality']-.10*min(9,(error/.04)**2))
                    else:self.bank.correct(p,phase_error,dt,quality,moving)
                else:self.bank.correct(p,phase_error,dt,quality,moving)
                observations[p.key]=record
            active=self.bank.choose(now,dt);mode=active.mode
            vision=self.swing if mode=='low_swing' else self.rotation;atlas=self.swing_atlas if mode=='low_swing' else self.rotation.atlas
            curve=atlas.curves(active.coordinate);record=observations.get(active.key)
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
                continuation='independent_chain_correction' if active.key in chain_corrected else 'visual_clock_correction' if valid else 'candidate_clock_correction' if active.visual else 'template_playback',status='tracking' if valid else 'coasting',
                coordinate='bounded_swing' if mode=='low_swing' else 'cyclic_rotation',angular_rate=2*math.pi*active.speed if mode=='low_swing' else None)
            self.previous=gray
            return dict(valid=False,avatar_valid=False,avatar_y=None,rope_valid=valid,rope_y=float(curve[20,1]) if valid else None,
                rope_points=[],whole_curve=curve.tolist(),whole_point_states=['measured' if x else 'predicted' if confidence>.25 else 'unknown' for x in support],whole_observed_points=visible.tolist(),
                whole_coverage=float(np.mean(support[2:-2])),phase_candidate_coverage=float(np.mean(support)),hand_anchors=[],model_exists=True,
                tracking_status=estimate['status'],track_id=1 if self.confirmed else 0,phase_estimate=estimate,
                phase_visual_quality=quality,phase_visual_candidate=candidate,phase_candidates_evaluated=sum(len(t['indices']) for t in self.tables.values() if t is not None),
                phase_alternatives=[dict(mode=p.mode,gear=p.gear,clock=p.phase,score=p.score) for p in sorted(self.bank.items,key=lambda p:p.score,reverse=True)[:4]],
                phase_atlas=atlas.name,phase_supported_mode='trajectory_gear_bank',motion_state=mode,mode_changes=self.bank.mode_switches,
                mode_candidate=self.bank.pending,entering_rotation_direction=self.bank.low_entry_direction if self.bank.low_entry_direction is not None else active.direction,exit_direction_prior=-self.bank.low_entry_direction if self.bank.low_entry_direction is not None else None,
                reacquisitions=0,last_motion_event=self.bank.event,phase_candidate_moving=moving,
                motion_speed=None,motion_phase='template_clock',motion_mode_candidate=mode,scene_changed=scene,
                selection_method='trajectory_gear_v4',rope_rejection=None if valid else 'model_not_visually_supported',terminal=None,mode_hint=None,
                clock_rate_evidence=self.clock_rate_proof,independent_exit_evidence=self.exit_beam_proof,independent_phase_evidence=self.phase_proof,phase_evidence_age=None if self.phase_proof_time is None else now-self.phase_proof_time,last_exit_recovered=self.bank.last_exit_recovered,estimated_transition_time=self.bank.estimated_transition_time,low_swing_episode=self.bank.low_episode,low_entry_direction=self.bank.low_entry_direction,low_turns_observed=sorted(self.bank.low_turns),low_played_cycles=self.bank.low_played_cycles,rotation_rearmed=self.bank.rotation_rearmed,rearm_visible_travel=self.bank.rearm_travel,model_selection_count=self.bank.switches,selected_hypothesis=active.key,gear_changes=self.bank.gear_switches,model_bank_size=len(self.bank.items),transition_boundary=self.boundary,speed_calibration_verified=False)
    return PhaseGearVision
