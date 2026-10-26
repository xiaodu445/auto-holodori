import json
import math
from pathlib import Path
import unittest
import numpy as np
from modular_agent.realtime.trajectory_bank import TrajectoryBank,AngularWarp,DirectionWarp
ROOT=Path(__file__).resolve().parents[1]
def settings():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_reverse_timing_config.json').read_text())

class ReverseTimingTests(unittest.TestCase):
    def test_front_half_slow_back_half_fast_with_positive_clock(self):
        b=TrajectoryBank(settings(),.65,.4);p=b.make('rotation_reverse',.65,0)
        w=b.reverse_warp;self.assertLess(w.evaluate(.5)[0],.5)
        p.phase=.65-.25;early=abs(p.coordinate_velocity);p.phase=.65-.75;late=abs(p.coordinate_velocity)
        self.assertGreater(late,early);self.assertGreater(p.speed,0)
    def test_coordinate_inverse_round_trip_across_ground_and_cycles(self):
        b=TrajectoryBank(settings(),.65,.4)
        for coordinate in np.linspace(-2.3,2.8,211):
            clock=b.rotation_clock('rotation_reverse',coordinate);p=b.make('rotation_reverse',clock,0)
            error=(p.coordinate-coordinate+.5)%1-.5;self.assertLess(abs(error),2e-6)
    def test_first_acquisition_keeps_observed_position(self):
        b=TrajectoryBank(settings(),.65,.4);b.acquire(.12,1,-1);p=next(x for x in b.items if x.key==b.active)
        self.assertAlmostEqual(p.coordinate,.12,places=5)
    def test_rotation_prediction_derivatives_match_geometry(self):
        b=TrajectoryBank(settings(),.65,.4);p=b.make('rotation_reverse',.65-.173,0)
        phase=p.phase;h=1e-5;v=p.coordinate_velocity;a=p.template_acceleration
        p.phase=phase-p.speed*h;future=p.coordinate;fv=p.coordinate_velocity
        p.phase=phase+p.speed*h;past=p.coordinate;pv=p.coordinate_velocity
        self.assertAlmostEqual((future-past)/(2*h),v,places=5);self.assertAlmostEqual((fv-pv)/(2*h),a,places=4)
    def test_coasting_uses_warp_without_visual_rate_inputs(self):
        b=TrajectoryBank(settings(),.65,.4);b.acquire(.65,0,-1);p=next(x for x in b.items if x.key==b.active)
        old=p.phase;speed=p.speed;b.advance(.02)
        self.assertAlmostEqual(p.phase,old-speed*.02);self.assertLess(p.coordinate_velocity,0)
    def test_forward_and_legacy_rotation_remain_linear(self):
        b=TrajectoryBank(settings(),.65,.4);p=b.make('rotation_forward',.17,0)
        self.assertEqual(p.coordinate,.17);self.assertEqual(p.coordinate_velocity,p.speed)
        c=settings();c.pop('reverse_time_profile');b=TrajectoryBank(c,.65,.4);p=b.make('rotation_reverse',.17,0)
        self.assertEqual(p.coordinate,.17);self.assertEqual(p.coordinate_velocity,-p.speed)
    def test_lookup_inverse_matches_bisection(self):
        c=settings()['reverse_time_profile'];slow=AngularWarp(c);fast=DirectionWarp(c)
        self.assertTrue(all(abs(slow.inverse(y)-fast.inverse(y))<2e-6 for y in np.linspace(0,.9999,301)))
    def test_invalid_reverse_profile_rejected(self):
        c=settings();c['reverse_time_profile']={'clock_nodes':[0,1],'angle_nodes':[0,0]}
        with self.assertRaises(ValueError):TrajectoryBank(c,.65,.4)
