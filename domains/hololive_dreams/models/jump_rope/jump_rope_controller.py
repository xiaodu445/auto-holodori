"""Predictive single-jump state machine. Unknown calibration never sends input."""
from collections import deque
import math
import numpy as np


class JumpRopeController:
    def __init__(self, config):
        self.c = config
        self.samples = deque(maxlen=config['fit_samples'])
        self.state = 'acquiring'
        self.mode = config['initial_mode']
        self.last_valid = None
        self.last_time = None
        self.last_speed = None
        self.pending = None
        self.release_at = None
        self.jump_sent_at = None
        self.ground_count = 0
        self.consumed = False
        self.jumps = 0
        self.crossings = 0
        self.previous_y = None
        self.last_prediction = None
        self.acquisition_started = None
        self.rope_stable = 0
        self.tracking_established = False
        self.demo_pass_consumed = False
        self.seen_returning=False

    def reset_motion(self):
        self.samples.clear()
        self.last_speed = self.pending = self.last_valid = self.last_time = None
        self.ground_count = 0
        self.state = 'acquiring'
        self.previous_y = None
        self.consumed = True
        self.last_prediction = None
        self.release_at = self.jump_sent_at = None
        self.seen_returning=False
        self.acquisition_started = None
        self.rope_stable = 0
        self.tracking_established = False

    def debug_snapshot(self):
        return dict(pass_consumed=self.demo_pass_consumed,seen_returning=self.seen_returning,
                    jump_outstanding=self.jump_sent_at is not None,ground_frames=self.ground_count,
                    motion_samples=len(self.samples),tracking_established=self.tracking_established)

    def calibrated(self):
        return self.c['calibration']['verified'] or self.c.get('experimental_input',False)

    def fit(self):
        if len(self.samples) < self.c['fit_samples']:
            return None
        times = np.array([p[0] for p in self.samples])
        values = np.array([p[1] for p in self.samples])
        if times[-1]-times[0] < .025:
            return None
        slope, offset = np.polyfit(times-times[-1], values, 1)
        error = float(np.max(np.abs(values-(slope*(times-times[-1])+offset))))
        return float(offset), float(slope), error

    def step(self, o, now, down=False, frame_age=0):
        d = dict(down=False, state=self.state, mode=self.mode, prediction=None,
                 pending=None, input_inhibited=None)
        if self.last_time is not None and now <= self.last_time:
            self.reset_motion(); d['input_inhibited'] = 'nonmonotonic_frame'; return d
        gap = 0 if self.last_time is None else now-self.last_time
        self.last_time = now
        if o.get('terminal') in ('success', 'failure'):
            # Only explicit boundary verification may populate terminal; CV does not invent it.
            d['stop'] = o['terminal']; return d
        if o.get('scene_changed'):
            self.reset_motion();d.update(down=False,input_inhibited='scene_changed_reacquiring')
            return d
        if frame_age > self.c['max_frame_age'] or gap > self.c['max_observation_gap']:
            self.samples.clear(); self.pending = None; self.ground_count = 0
            d['input_inhibited'] = 'stale_or_gap'; return d
        # Key release is independent of jump/rope recognition. Never keep space held under loss.
        if down and self.release_at is not None and now < self.release_at and (o.get('valid') or self.c.get('demonstration_crossing_trial') and o.get('avatar_valid')):
            d['down'] = True
        avatar_y = o.get('avatar_y')
        baseline = self.c['avatar_template'][1]
        grounded = o.get('avatar_valid') and avatar_y is not None and abs(avatar_y-baseline) <= self.c['ground_tolerance']
        self.ground_count = self.ground_count+1 if grounded else 0
        if self.tracking_established and o.get('avatar_valid') and avatar_y is not None and avatar_y < baseline-self.c['ground_tolerance']:
            self.state = 'airborne'
        elif self.tracking_established and self.ground_count >= self.c['ground_frames']:
            if self.state == 'airborne': self.jump_sent_at = None
            if self.jump_sent_at is None and self.state != 'recovering': self.state = 'grounded'
        if o.get('valid') and self.jump_sent_at is not None and self.state != 'airborne' and now-self.jump_sent_at > .3:
            self.jump_sent_at=self.release_at=self.pending=None
            self.samples.clear();self.last_speed=self.last_prediction=None
            self.state='grounded' if grounded else 'recovering'
            d.update(down=False,state=self.state,input_inhibited='jump_confirmation_missing',
                     warning='jump_not_observed_continuing')
            return d
        if self.acquisition_started is None: self.acquisition_started = now
        reliable = o.get('rope_valid') and o.get('avatar_valid')
        self.rope_stable = self.rope_stable+1 if reliable else 0
        if self.rope_stable >= self.c.get('rope_stable_frames',3):
            self.tracking_established = True
            if self.state in ('recovering','waiting_for_rope','acquiring'):
                self.state = 'grounded' if self.ground_count >= self.c['ground_frames'] else 'airborne' if avatar_y is not None and avatar_y < baseline-self.c['ground_tolerance'] else 'acquiring'
        if not self.tracking_established:
            self.pending = None; d['down'] = False
            self.state = 'recovering' if self.state == 'recovering' else 'waiting_for_rope'
            d.update(state=self.state,input_inhibited='reacquiring_track' if self.state == 'recovering' else 'initial_rope_not_acquired',
                     acquisition_seconds=now-self.acquisition_started)
            if now-self.acquisition_started >= self.c.get('acquisition_timeout',20):
                d['input_inhibited'] = 'searching_for_track'
            d['missing_features'] = [key for key in ('avatar','rope') if not o.get(key+'_valid')]
            return d
        if not reliable:
            d['missing_features'] = [key for key in ('avatar','rope') if not o.get(key+'_valid')]
            self.pending = None
            if not o.get('avatar_valid'):d['down'] = False
            elapsed = now-(self.last_valid if self.last_valid is not None else self.samples[0][0] if self.samples else now)
            if elapsed > self.c['long_loss_seconds']:
                # Discard stale control history, continue visual acquisition within session timeout.
                self.reset_motion()
                self.release_at = self.jump_sent_at = None
                self.state = 'recovering'
                self.acquisition_started = now
                d.update(state=self.state,input_inhibited='reacquiring_track')
                return d
            if (self.c.get('demonstration_crossing_trial') and self.mode=='rotation'
                    and o.get('motion_mode',o.get('mode_hint')) not in ('swing','unknown')
                    and not o.get('rope_valid') and grounded
                    and self.ground_count>=self.c['ground_frames']
                    and self.jump_sent_at is None and not self.demo_pass_consumed
                    and len(self.samples)>=3):
                recent=list(self.samples)[-3:]
                age=now-recent[-1][0]
                times=np.array([p[0] for p in recent]);values=np.array([p[1] for p in recent])
                if (0<age<=min(.12,self.c.get('occlusion_prediction_seconds',.12))
                        and np.max(np.diff(times))<=self.c['max_observation_gap']
                        and times[-1]-times[0]>=.025):
                    speed,position=np.polyfit(times-times[-1],values,1)
                    error=float(np.max(np.abs(values-(speed*(times-times[-1])+position))))
                    speeds=np.diff(values)/np.diff(times)
                    stable=abs(speeds[-1]-speeds[-2])<=max(.15,abs(speed)*.4)
                    predicted=float(position+speed*age)
                    if (speed>.15 and stable and error<=.006
                            and baseline-.20<=predicted<baseline+.025):
                        self.demo_pass_consumed=True;self.consumed=True
                        self.jumps+=1;self.jump_sent_at=now
                        self.release_at=now+self.c['pulse_seconds'];self.state='jump_requested'
                        d.update(down=True,state=self.state,jumps=self.jumps,input_inhibited=None,
                            trigger='short_occlusion_prediction_trial',
                            prediction=dict(historical=True,age=age,speed=float(speed),
                                rope_y=predicted,error=error))
                        return d
            # Short-term historical estimates are diagnostic only until a calibrated error bound exists.
            if elapsed <= self.c['short_loss_seconds'] and self.last_prediction is not None:
                d['prediction'] = {**self.last_prediction, 'historical': True, 'age': elapsed}
            d['input_inhibited'] = 'avatar_unavailable' if o.get('rope_valid') else 'rope_unavailable' if o.get('avatar_valid') else 'avatar_and_rope_unavailable'; return d
        self.last_valid = now
        # Only geometric/motion evidence may suggest a mode; color has no control role.
        hint = o.get('motion_mode', o.get('mode_hint'))
        if hint in ('rotation', 'swing') and hint != self.mode:
            self.mode = hint; self.samples.clear(); self.pending = None; self.consumed = True
        d.update(state=self.state,mode=self.mode)
        y = o['rope_y']
        if self.samples and now-self.samples[-1][0]>self.c['max_observation_gap']:
            self.samples.clear();self.pending=None;self.last_speed=None
        self.samples.append((now, y))
        # Early visible-phase trial avoids requiring the frequently occluded foot segment.
        if self.c.get('demonstration_crossing_trial') and self.mode == 'rotation':
            if y < baseline-.25:self.demo_pass_consumed=False
            # A sustained upward then downward trace also confirms a new rotation
            # when the exact overhead height was hidden. No time-only rearming.
            if len(self.samples)>=3:
                recent=list(self.samples)[-3:]
                times=np.array([point[0] for point in recent])
                speeds=np.diff([point[1] for point in recent])/np.diff(times)
                if np.all(speeds<-.15):self.seen_returning=True
                elif self.seen_returning and np.all(speeds>.15):
                    self.demo_pass_consumed=False;self.consumed=False
                    self.seen_returning=False
            if len(self.samples)>=2:
                before_time,before_y=self.samples[-2]
                dt=now-before_time
                threshold=baseline-.20
                speed=(y-before_y)/dt if dt>0 else 0
                d.update(motion_speed=speed,motion_direction=1 if speed>0 else -1 if speed<0 else 0)
                if (self.c.get('visible_trial_coherent',True) and threshold<=y<baseline+.025 and speed>.15
                        and grounded and self.ground_count>=self.c['ground_frames']
                        and self.jump_sent_at is None and not self.demo_pass_consumed):
                    self.demo_pass_consumed=True
                    self.jumps+=1;self.consumed=True;self.jump_sent_at=now
                    self.release_at=now+self.c['pulse_seconds']
                    self.state='jump_requested'
                    d.update(down=True,state=self.state,jumps=self.jumps,
                             input_inhibited=None,trigger='demonstration_crossing_trial')
                    return d
        fit = self.fit()
        calibration = self.c['calibration']
        danger = calibration['danger_y']
        if danger is not None:
            if self.previous_y is not None and (y-danger)*(self.previous_y-danger) < 0:
                self.crossings += 1
            if abs(y-danger) > .035: self.consumed = False
        self.previous_y = y
        if fit is None:
            d['input_inhibited'] = 'acquiring_motion'; return d
        position, speed, error = fit
        d.update(motion_speed=speed,motion_direction=1 if speed>0 else -1 if speed<0 else 0,fit_error=error)
        if self.last_speed is not None and abs(speed-self.last_speed) > max(.1, abs(self.last_speed)*self.c['speed_change_ratio']):
            self.pending = None
            self.last_speed = speed
            d['input_inhibited'] = 'speed_changed'; return d
        self.last_speed = speed
        if danger is None or abs(speed) < .03:
            d['input_inhibited'] = 'danger_not_calibrated' if danger is None else 'turning'
            self.pending = None; return d
        eta = (danger-position)/speed
        self.last_prediction = dict(arrival=now+eta, eta=eta, speed=speed, error=error,
                                    direction=1 if speed > 0 else -1, historical=False)
        d['prediction'] = self.last_prediction
        if not self.calibrated():
            d['input_inhibited'] = 'calibration_unverified'; return d
        if self.mode == 'unknown':
            self.pending = None; d['input_inhibited'] = 'skill_mode_unknown'; return d
        if self.mode == 'rotation' and (1 if speed > 0 else -1) != calibration['rotation_direction']:
            self.pending = None; d['input_inhibited'] = 'safe_rotation_pass'; return d
        # Swing is an independent bidirectional crossing model; never use a full-rotation period.
        if error > calibration['max_prediction_error'] or not 0 < eta <= self.c['prediction_horizon']:
            self.pending = None; d['input_inhibited'] = 'prediction_uncertain'; return d
        safe_air = calibration['safe_airborne_seconds']
        lead = calibration['input_latency_seconds'] + safe_air/2
        self.pending = now+eta-lead  # Replaced each fresh frame; no sleeping queued action.
        d['pending'] = self.pending
        if self.pending <= now and grounded and self.ground_count >= self.c['ground_frames'] and self.jump_sent_at is None and not self.consumed:
            self.jumps += 1; self.consumed = True; self.jump_sent_at = now
            self.release_at = now+self.c['pulse_seconds']; self.pending = None
            self.state = 'jump_requested'; d['down'] = True
        d.update(state=self.state, mode=self.mode, jumps=self.jumps, crossings=self.crossings)
        return d
