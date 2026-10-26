"""Reusable cyclic trajectory and phase estimator; no CV, window or input calls."""
import math
import numpy as np


class CyclicTrajectory:
    def __init__(self, data):
        if data.get('schema') != 1 or data.get('mode') != 'rotation':
            raise ValueError('only rotation atlas schema 1 is supported')
        samples=data.get('samples',[])
        self.phases=np.array([s['phase'] for s in samples],dtype=float)
        self.points=np.array([s['curve'] for s in samples],dtype=float)
        if len(samples)<4 or self.points.ndim!=3 or self.points.shape[1:]!=(41,2):
            raise ValueError('atlas requires at least four 41-point curves')
        if not np.all(np.isfinite(self.points)) or not np.all(np.isfinite(self.phases)):
            raise ValueError('nonfinite atlas')
        if self.phases[0]!=0 or np.any(np.diff(self.phases)<=0) or self.phases[-1]>=1:
            raise ValueError('atlas phases must increase from 0 to below 1')
        if np.any(self.points<-.2) or np.any(self.points>1.2):raise ValueError('atlas outside normalized client bounds')
        self.period=float(data['reference_period'])
        if not math.isfinite(self.period) or not .1<self.period<10:raise ValueError('invalid atlas period')
        self.name=data.get('name','unnamed')
        self._phases=np.r_[self.phases,1.0]
        self._points=np.concatenate([self.points,self.points[:1]])

    def curves(self, phases):
        wrapped=np.asarray(phases,dtype=float)%1
        indices=np.searchsorted(self._phases,wrapped,side='right')-1
        weights=(wrapped-self._phases[indices])/(self._phases[indices+1]-self._phases[indices])
        return self._points[indices]*(1-weights[...,None,None])+self._points[indices+1]*weights[...,None,None]


class PhaseTracker:
    """Always retains a hypothesis. Image support and hypothesis existence differ."""
    def __init__(self, nominal_rate, *, max_rate=4.0, max_acceleration=8.0):
        if not all(math.isfinite(x) and x>0 for x in (nominal_rate,max_rate,max_acceleration)):
            raise ValueError('invalid phase rates')
        self.nominal_rate=nominal_rate;self.max_rate=max_rate;self.max_acceleration=max_acceleration
        self.reset()

    def reset(self):
        self.phase=0.;self.rate=self.nominal_rate;self.time=None
        self.last_visual=None;self.confidence=0.;self.uncertainty=.5;self.locked=False
        self.pending=None;self.pending_time=None;self.pending_count=0

    def predict(self, now):
        if not math.isfinite(now) or self.time is not None and now<=self.time:
            raise ValueError('nonmonotonic phase clock')
        dt=0 if self.time is None else now-self.time
        return self.phase+self.rate*dt

    @staticmethod
    def nearest(phase, prediction):
        return float(phase)+round(prediction-float(phase))

    def update(self, now, visual_phase=None, quality=0.):
        predicted=self.predict(now);dt=0 if self.time is None else now-self.time
        if not math.isfinite(quality) or not 0<=quality<=1:raise ValueError('invalid phase quality')
        if visual_phase is not None and not math.isfinite(visual_phase):raise ValueError('invalid visual phase')
        self.confidence*=math.exp(-dt/.65)
        self.uncertainty=min(.5,self.uncertainty+dt*(.035+.05*self.rate))
        observed=False
        if visual_phase is not None and quality>=.30:
            measured=self.nearest(visual_phase,predicted)
            if not self.locked:
                if self.pending is None or self.pending_time is None or now-self.pending_time>.08:
                    self.pending_count=1
                else:
                    measured=self.nearest(visual_phase,self.pending+self.rate*(now-self.pending_time))
                    step=measured-self.pending
                    self.pending_count=self.pending_count+1 if -.025<=step<=self.max_rate*(now-self.pending_time)+.04 else 1
                self.pending=measured;self.pending_time=now
                if self.pending_count>=3:
                    self.locked=True;predicted=measured;observed=True
            else:
                error=measured-predicted
                gate=min(.30,.06+self.uncertainty)
                # Correct phase, never individual curve points. Corrections and
                # rate changes are bounded; no instantaneous alternate-arc swap.
                correction=max(-min(.025,dt),min(min(.025,dt),error*.45))
                predicted=max(self.phase,predicted+correction)
                if dt and dt<=.08:
                    change=max(-self.max_acceleration*dt,min(self.max_acceleration*dt,.16*error/dt))
                    self.rate=max(.02,min(self.max_rate,self.rate+change))
                observed=abs(error)<=gate
            if observed:
                self.last_visual=now;self.confidence=.7*self.confidence+.3*quality
                self.uncertainty=max(.012,self.uncertainty*.6)
        else:
            if self.pending_time is not None and now-self.pending_time>.08:
                self.pending=None;self.pending_time=None;self.pending_count=0
        self.phase=predicted;self.time=now
        age=None if self.last_visual is None else now-self.last_visual
        return dict(phase=self.phase%1,phase_unwrapped=self.phase,rate=self.rate,
            confidence=self.confidence,uncertainty=self.uncertainty,observed=observed,
            observation_age=age,locked=self.locked,
            status='tracking' if observed else 'acquiring' if not self.locked else 'coasting' if age is not None and age<.5 else 'searching_with_prediction')


class SignedPhaseTracker(PhaseTracker):
    """Opt-in signed motion; reversal requires a coherent multi-frame slope.

    The original forward-only estimator is intentionally left unchanged.
    Phase is unwrapped relative to recent measurements, not image height.
    """
    def reset(self):
        super().reset()
        self.history = []
        self.direction = 1
        self.reverse_pending = 0
        self.reversals = 0
        self.measured_rate = None

    def _slope(self):
        if len(self.history) < 4:
            return None, False
        times = np.array([item[0] for item in self.history])
        values = np.array([item[1] for item in self.history])
        weights = np.array([item[2] for item in self.history])
        if times[-1] - times[0] < .065:
            return None, False
        times = times - times[-1]
        center = np.average(times, weights=weights)
        mean = np.average(values, weights=weights)
        slope = np.sum(weights * (times-center) * (values-mean)) / max(1e-9, np.sum(weights * (times-center)**2))
        residual = np.sqrt(np.average((values-mean-slope*(times-center))**2, weights=weights))
        differences = np.diff(values)
        moving = differences[abs(differences) > .002]
        coherence = np.mean(moving * slope > 0) if len(moving) else 0
        coherent = residual <= .018 and coherence >= .70 and abs(values[-1]-values[0]) >= .018
        return float(np.clip(slope, -self.max_rate, self.max_rate)), coherent

    def update(self, now, visual_phase=None, quality=0.):
        predicted = self.predict(now)
        dt = 0 if self.time is None else now-self.time
        if not math.isfinite(quality) or not 0 <= quality <= 1:
            raise ValueError('invalid phase quality')
        if visual_phase is not None and not math.isfinite(visual_phase):
            raise ValueError('invalid visual phase')
        self.confidence *= math.exp(-dt/.65)
        self.uncertainty = min(.5, self.uncertainty + dt*(.035+.05*abs(self.rate)))
        observed = False
        if self.history and now-self.history[-1][0] > .12:
            self.history = []
            self.reverse_pending = 0
        if visual_phase is not None and quality >= .30:
            measured = self.nearest(visual_phase, predicted)
            # Reject before any phase/rate/history update. Old prediction continues.
            gate = min(.30, .10+2*self.uncertainty)
            acceptable = not self.locked or abs(measured-predicted) <= gate
            if self.history:
                elapsed = now-self.history[-1][0]
                measured = self.nearest(visual_phase, self.history[-1][1]+self.rate*elapsed)
                continuous = abs(measured-self.history[-1][1]) <= self.max_rate*elapsed+.015
                # A coherent visual chain may turn away from a forward prediction.
                # Keep collecting it so the turn can be confirmed before correcting direction.
                acceptable = (acceptable or self.locked and elapsed <= .08) and continuous
            if acceptable:
                self.history.append((now, measured, quality))
                self.history = [item for item in self.history if now-item[0] <= .18][-10:]
                slope, coherent = self._slope()
                self.measured_rate = slope
                if not self.locked:
                    if len(self.history) >= 3:
                        self.locked = True
                        predicted = measured
                        if slope is not None and coherent and abs(slope) > .06:
                            self.direction = 1 if slope > 0 else -1
                            self.rate = slope
                        observed = True
                else:
                    if coherent and slope*self.direction < -.06:
                        self.reverse_pending += 1
                    else:
                        self.reverse_pending = 0
                    if self.reverse_pending >= 3:
                        self.direction *= -1
                        self.reversals += 1
                        self.reverse_pending = 0
                    if slope is not None and dt and dt <= .08:
                        # A pending turn may slow to zero, but cannot reverse from one outlier.
                        target = slope if slope*self.direction >= 0 else 0.
                        change = np.clip((target-self.rate)*.40, -self.max_acceleration*dt, self.max_acceleration*dt)
                        self.rate = float(np.clip(self.rate+change, -self.max_rate, self.max_rate))
                        if self.rate*self.direction < 0:
                            self.rate = 0.
                    correction = float(np.clip((measured-predicted)*.45, -min(.025,dt), min(.025,dt)))
                    predicted += correction
                    # Preserve continuity in the confirmed direction, including at the turn.
                    predicted = max(self.phase,predicted) if self.direction > 0 else min(self.phase,predicted)
                    observed = True
                if observed:
                    self.last_visual = now
                    self.confidence = .7*self.confidence+.3*quality
                    self.uncertainty = max(.012,self.uncertainty*.6)
        self.phase = float(predicted)
        self.time = now
        age = None if self.last_visual is None else now-self.last_visual
        return dict(phase=self.phase%1,phase_unwrapped=self.phase,rate=self.rate,
            confidence=self.confidence,uncertainty=self.uncertainty,observed=observed,
            observation_age=age,locked=self.locked,direction=self.direction,
            reversal_pending=self.reverse_pending,reversals=self.reversals,measured_rate=self.measured_rate,
            status='tracking' if observed else 'acquiring' if not self.locked else 'coasting' if age is not None and age<.5 else 'searching_with_prediction')
