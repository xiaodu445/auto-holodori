"""Legal cyclic/bounded motion hypotheses; baseline signed tracker is unchanged."""
import math
import numpy as np
from modular_agent.realtime.phase_tracking import SignedPhaseTracker


class LegalSignedTracker(SignedPhaseTracker):
    def __init__(self,nominal_rate,*,max_rate=4.,max_acceleration=8.,zero_timeout=.65):
        if not math.isfinite(zero_timeout) or not .1<zero_timeout<2:raise ValueError('invalid zero timeout')
        self.zero_timeout=zero_timeout
        super().__init__(nominal_rate,max_rate=max_rate,max_acceleration=max_acceleration)

    def reset(self):
        super().reset()
        self.good_rate = self.nominal_rate
        self.weak_since = None
        self.zero_since = None
        self.search_wide = False
        self.recovery_count = 0
        self.motion_supported = False
        self.blocked_correction = False

    def feedback(self, supported, now):
        self.motion_supported = bool(supported)
        if supported:
            self.weak_since = None
            if self.rate*self.direction > .12:
                self.good_rate = abs(self.rate)
        elif self.weak_since is None:
            self.weak_since = now
        if not supported:
            # A supported candidate does not validate a different output curve.
            self.confidence *= .35 if self.weak_since is not None and now-self.weak_since >= .12 else .82
            self.uncertainty = min(.5, max(.15 if self.weak_since is not None and now-self.weak_since >= .12 else 0.,self.uncertainty+.015))
        self.search_wide = self.locked and (self.weak_since is not None and now-self.weak_since >= .12 or self.zero_since is not None and now-self.zero_since >= .30)

    def update(self, now, visual_phase=None, quality=0.):
        previous_phase = self.phase
        previous_rate = self.rate
        previous_direction = self.direction
        dt = 0 if self.time is None else now-self.time
        was_recovery = self.search_wide
        result = super().update(now,visual_phase,quality)
        self.blocked_correction = False
        # In rotation, dubious position correction cannot erase predicted travel.
        # A measured slowdown or pending reversal still may approach zero briefly.
        if result['locked'] and self.direction == previous_direction and abs(previous_rate) > .05 and abs(self.rate) > .05 and not self.reverse_pending:
            minimum = abs(previous_rate)*dt*.25
            if self.direction*(self.phase-previous_phase) < minimum:
                self.phase = previous_phase+self.direction*minimum
                self.blocked_correction = True
        if abs(self.rate) < .06:
            if self.zero_since is None:self.zero_since = now
        else:self.zero_since = None
        if self.locked and self.zero_since is not None and now-self.zero_since > self.zero_timeout:
            # Long zero rate is invalid in rotation: resume a marked hypothesis,
            # widen image search and do not claim that the rope was observed.
            self.rate = self.direction*max(.12,self.good_rate)
            self.phase = previous_phase+self.rate*dt
            self.confidence *= .5
            self.uncertainty = max(.15,self.uncertainty)
            self.search_wide = True
            self.zero_since = None
            self.recovery_count += 1
            result['observed'] = False
        if was_recovery and not self.search_wide:self.recovery_count += 1
        result.update(phase=self.phase%1,phase_unwrapped=self.phase,rate=self.rate,
            confidence=self.confidence,uncertainty=self.uncertainty,
            search_wide=self.search_wide,blocked_correction=self.blocked_correction,
            motion_supported=self.motion_supported,recovery_count=self.recovery_count)
        return result


class BoundedSwingTracker(SignedPhaseTracker):
    """A finite pendulum coordinate. Lost images use a bounded smooth prior.

    Coordinate 0..1 is not cyclic phase. Angular rate is adapted from visible
    motion away from endpoints; it is a prediction, never an input schedule.
    """
    def __init__(self, period, *, max_rate=4., max_acceleration=8.,zero_timeout=.65):
        if not math.isfinite(period) or not .4 < period < 10:
            raise ValueError('invalid swing period')
        if not math.isfinite(zero_timeout) or not .1<zero_timeout<2:raise ValueError('invalid zero timeout')
        self.zero_timeout=zero_timeout
        self.reference_period = period
        super().__init__(math.pi/period,max_rate=max_rate,max_acceleration=max_acceleration)

    def reset(self):
        super().reset()
        self.phase = .5
        self.omega = min(2*math.pi/self.reference_period,2*self.max_rate)
        self.predicted_turns = 0
        self.motion_supported = False
        self.weak_since = None
        self.search_wide = False
        self.zero_since = None

    @staticmethod
    def nearest(phase,prediction):
        return float(phase)

    def _prediction(self, now):
        if not math.isfinite(now) or self.time is not None and now <= self.time:
            raise ValueError('nonmonotonic phase clock')
        dt = 0 if self.time is None else now-self.time
        angle = math.acos(np.clip(1-2*self.phase,-1,1))
        if self.direction < 0:angle = 2*math.pi-angle
        angle += self.omega*dt
        return (1-math.cos(angle))/2,.5*self.omega*math.sin(angle)

    def predict(self,now):
        return self._prediction(now)[0]

    def feedback(self,supported,now):
        self.motion_supported = bool(supported)
        if supported:self.weak_since = None
        elif self.weak_since is None:self.weak_since = now
        if not supported:
            self.confidence *= .35 if self.weak_since is not None and now-self.weak_since >= .12 else .82
            self.uncertainty = min(.5,self.uncertainty+.015)
        self.search_wide = self.locked and self.weak_since is not None and now-self.weak_since >= .12

    def update(self,now,visual_phase=None,quality=0.):
        if visual_phase is not None and not 0 <= visual_phase <= 1:
            raise ValueError('swing coordinate outside bounds')
        prediction,velocity = self._prediction(now)
        # The pendulum may stop briefly at its ends, not indefinitely halfway.
        if self.zero_since is not None and now-self.zero_since>.12 and .10<self.phase<.90:
            visual_phase=None;quality=0.
            self.search_wide=True
        old_direction = self.direction
        if self.locked and velocity*old_direction < -.001 and (self.phase < .04 or self.phase > .96 or not self.motion_supported):
            self.direction = 1 if velocity > 0 else -1
            self.rate = velocity
            self.predicted_turns += 1
        result = super().update(now,visual_phase,quality)
        self.phase = float(np.clip(self.phase,0,1))
        if result['observed'] and self.motion_supported and self.measured_rate is not None and .12 < self.phase < .88 and self.measured_rate*self.direction > .06:
            denominator = max(.2,math.sqrt(self.phase*(1-self.phase)))
            omega = float(np.clip(abs(self.measured_rate)/denominator,2*math.pi/6,min(2*self.max_rate,2*math.pi/.8)))
            self.omega = .85*self.omega+.15*omega
        if not result['observed']:
            self.phase = prediction
            self.rate = velocity
        # Near endpoints the velocity must approach zero and then resume, not
        # persist as a stopped cyclic hypothesis. Confidence follows image evidence.
        if abs(self.rate) < .06:
            if self.zero_since is None:self.zero_since = now
            if now-self.zero_since > self.zero_timeout:
                self.phase = prediction
                self.rate = velocity
                result['observed'] = False
                self.confidence *= .5
                self.uncertainty = max(.15,self.uncertainty)
                self.search_wide = True
        else:self.zero_since = None
        result.update(phase=self.phase,phase_unwrapped=self.phase,rate=self.rate,
            confidence=self.confidence,uncertainty=self.uncertainty,
            direction=self.direction,predicted_turns=self.predicted_turns,
            search_wide=self.search_wide,motion_supported=self.motion_supported,
            coordinate='bounded_swing',angular_rate=self.omega)
        return result


class BoundedTrajectory:
    def __init__(self,data):
        if data.get('schema') != 1 or data.get('mode') != 'low_swing':
            raise ValueError('invalid low swing atlas')
        self.coordinates = np.array([s['coordinate'] for s in data['samples']],dtype=float)
        self.points = np.array([s['curve'] for s in data['samples']],dtype=float)
        if len(self.coordinates)<4 or self.points.shape != (len(self.coordinates),41,2):
            raise ValueError('invalid low swing curves')
        if not np.all(np.isfinite(self.points)) or not np.all(np.isfinite(self.coordinates)):
            raise ValueError('nonfinite low swing atlas')
        if self.coordinates[0]!=0 or self.coordinates[-1]!=1 or np.any(np.diff(self.coordinates)<=0):
            raise ValueError('invalid low swing coordinates')
        if np.any(self.points<0) or np.any(self.points>1):raise ValueError('low swing outside client')
        self.period = float(data['reference_period'])
        if not math.isfinite(self.period) or not .4<self.period<10:raise ValueError('invalid swing period')
        self.name = data.get('name','low_swing')

    def curves(self,coordinates):
        values=np.clip(np.asarray(coordinates,dtype=float),0,1)
        indices=np.minimum(np.searchsorted(self.coordinates,values,side='right')-1,len(self.coordinates)-2)
        weight=(values-self.coordinates[indices])/(self.coordinates[indices+1]-self.coordinates[indices])
        return self.points[indices]*(1-weight[...,None,None])+self.points[indices+1]*weight[...,None,None]
