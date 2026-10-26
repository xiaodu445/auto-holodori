"""Normalized-position predictive fishing controller."""
from collections import deque
import numpy as np

class FishingController:
    def __init__(self, config):
        self.config=config
        self.history=deque(maxlen=config['velocity_samples'])
        self.velocity=0
        self.cycle_start=None
        self.cycle_duty=0
    def reset(self):
        self.history.clear(); self.velocity=0
        self.cycle_start=None; self.cycle_duty=0
    def decide(self, observation, now, down):
        self.history.append((now,observation['center']))
        if len(self.history)>1:
            t,p=self.history[0]; dt=now-t
            raw=(observation['center']-p)/max(dt,1e-6)
            raw=float(np.clip(raw,-self.config['max_speed'],self.config['max_speed']))
            a=self.config['velocity_alpha']
            self.velocity=a*raw+(1-a)*self.velocity
        predicted=observation['center']+self.velocity*self.config['lookahead_seconds']
        margin=observation['bar_height']*self.config['inside_margin']
        error=predicted-observation['fish']
        # Image y grows downward: hold when predicted bar is below fish.
        request=down if abs(error)<=margin else error>0
        target_velocity=None
        braking=False
        if self.config.get('inertia_braking',False) and self.config.get('control_mode','bang_bang')=='bang_bang':
            # Approach the target slowly; brake while still inside the bar.
            # y increases downward. Holding accelerates upward, release brakes ascent.
            position_error=observation['center']-observation['fish']
            target_velocity=float(np.clip(-position_error/self.config['approach_seconds'],
                                         -self.config['approach_max_speed'],self.config['approach_max_speed']))
            speed_error=self.velocity-target_velocity
            threshold=self.config['velocity_deadband']
            if speed_error>threshold:
                request=True
            elif speed_error < -threshold:
                request=False
            # Near target speed, use the existing prediction/hysteresis decision.
            braking=(request != (position_error>0))
        edge=self.config['edge_margin']
        # Brake before high-speed impact; model is deliberately tunable, not a calibrated physics claim.
        if observation['bar_top']<edge and self.velocity < -self.config['edge_speed']: request=False
        if observation['bar_bottom']>1-edge and self.velocity > self.config['edge_speed']: request=True
        duty=None
        if self.config.get('control_mode','bang_bang')=='pwm':
            # Positive y velocity is falling: add upward effort to brake it.
            duty=float(np.clip(self.config['pwm_hover_duty']
                  +self.config['pwm_position_gain']*(observation['center']-observation['fish'])
                  +self.config['pwm_velocity_gain']*self.velocity,
                  self.config['pwm_min_duty'],self.config['pwm_max_duty']))
            period=self.config['pwm_period_seconds']
            # Freeze duty within a cycle so changing error cannot create extra pulses.
            if self.cycle_start is None or now-self.cycle_start>=period:
                self.cycle_start=now
                # Restart missed cycles at now; never replay stale pulses in a burst.
                self.cycle_duty=duty
            request=now-self.cycle_start < period*self.cycle_duty
            # Boundary braking takes priority over the pulse schedule.
            if observation['bar_top']<edge and self.velocity < -self.config['edge_speed']: request=False
            if observation['bar_bottom']>1-edge and self.velocity > self.config['edge_speed']: request=True
        return dict(down=bool(request),velocity=self.velocity,predicted=predicted,error=error,
                    target_velocity=target_velocity,braking=braking,
                    duty=duty,cycle_duty=self.cycle_duty if duty is not None else None)

