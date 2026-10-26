"""Independent C4: template clocks, bounded gear rates and boundary model bank."""
import math
import time
import numpy as np
import cv2
from modular_agent.realtime.trajectory_bank import TrajectoryBank


# Loader supplies C3 only for its shared local image features, not its decisions.
def gear_vision_type(base):
    class PhaseGearVision(base):
        def reset(self):
            super().reset()
            curves=self.rotation.atlas.curves(np.arange(2048)/2048)
            self.boundary=float(np.argmax(curves[:,20,1])/2048)
            distances=np.mean(np.linalg.norm(self.swing.reference_curves-curves[round(self.boundary*2048)],axis=2),axis=1)
            entry=float(self.swing.grid[int(np.argmin(distances))])
            self.entry_angle=math.acos(1-2*entry)/(2*math.pi)
            self.bank=TrajectoryBank(self.settings,self.boundary,self.entry_angle)
            self.acquisition_chain=type(self.alternative_chain)(True)
            self.tables={};self.last_quality=0.;self.confirmed=False
            self.exit_chain=type(self.alternative_chain)(True)

        def evidence_table(self,vision,gray,indices):
            indices=np.unique(indices).astype(int)
            q,raw,seen,coverage,moving=self._evidence(vision,gray,indices)
            return dict(indices=indices,q=q,raw=raw,seen=seen,coverage=coverage,moving=moving)

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
            moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
            self.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);self.variation=self.high-self.low
            self.rotation.prepare(gray);self.swing.prepare(gray);self.frame_count+=1
            if not self.bank.items:
                self.bank.acquire(0.,now);self.bank.locked=False
                dt=0.
            else:dt=self.bank.advance(now)
            active_before=next(p for p in self.bank.items if p.key==self.bank.active)
            global_search=not self.confirmed or self.bank.weak_seconds>.15 and self.frame_count%10==0
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
                records=self.exit_chain.records
                if len(records)>=5 and now-records[0][0]>=.12 and records[-1][0]==now:
                    expected=-self.bank.low_entry_direction;slope=self.exit_chain.slope()
                    ts=np.array([r[0] for r in records]);xs=np.array([r[1] for r in records]);ts-=ts[-1]
                    fit=np.polyfit(ts,xs,1);residual=float(np.sqrt(np.mean((xs-np.polyval(fit,ts))**2)))
                    if slope is not None and slope*expected>.3 and (xs[-1]-xs[0])*expected>.06 and residual<.012:
                        self.bank.reconstruct_exit(float(phases[j]),abs(slope),now)
            else:self.exit_chain=type(self.alternative_chain)(True)
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
                        else:phase_error=float(gap[j])
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
                self.bank.correct(p,phase_error,dt,quality,moving)
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
                continuation='visual_clock_correction' if valid else 'candidate_clock_correction' if active.visual else 'template_playback',status='tracking' if valid else 'coasting',
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
                last_exit_recovered=self.bank.last_exit_recovered,estimated_transition_time=self.bank.estimated_transition_time,low_swing_episode=self.bank.low_episode,low_entry_direction=self.bank.low_entry_direction,low_turns_observed=sorted(self.bank.low_turns),low_played_cycles=self.bank.low_played_cycles,rotation_rearmed=self.bank.rotation_rearmed,rearm_visible_travel=self.bank.rearm_travel,rearm_played_cycles=self.bank.rearm_played_cycles,rearm_upper_travel=self.bank.rearm_upper_travel,model_selection_count=self.bank.switches,selected_hypothesis=active.key,gear_changes=self.bank.gear_switches,model_bank_size=len(self.bank.items),transition_boundary=self.boundary,speed_calibration_verified=False)
    return PhaseGearVision
