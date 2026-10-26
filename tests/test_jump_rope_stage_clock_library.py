import json
from pathlib import Path
import unittest
import numpy as np
from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank
from modular_agent.realtime.build_jump_rope_clock_library import fit,temporal_contrast
ROOT=Path(__file__).resolve().parents[1]
def bank():
    c=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_stage_clock_library_config.json').read_text())
    profiles=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/stage_clock_library_v1_trial.json').read_text())
    return StagedTrajectoryBank(c,.4140625,.4,profiles)
class StageClockLibraryTests(unittest.TestCase):
    def test_role_names_and_unmeasured_status_are_explicit(self):
        b=bank();b.set_stage(2,0)
        self.assertEqual([b.role(b.make('rotation_reverse',.2,i)) for i in range(3)],['decelerate','normal','accelerate'])
        self.assertEqual(b.profile_status(b.make('rotation_reverse',.2,0)),'pending_calibration')
    def test_acquisition_profiles_share_observed_geometry(self):
        for direction in [-1,1]:
            b=bank();b.set_stage(2,0);b.acquire(.12,.01,direction)
            self.assertTrue(all(abs((p.coordinate-.12+.5)%1-.5)<2e-6 for p in b.items))
    def test_each_stage_role_direction_inverse_round_trip(self):
        b=bank()
        for stage in range(5):
            if stage:b.set_stage(stage,stage)
            for mode in ['rotation_forward','rotation_reverse']:
                for gear in range(3):
                    for coordinate in [.01,.2,.47,.71,.99]:
                        clock=b.rotation_clock(mode,coordinate,gear);p=b.make(mode,clock,gear)
                        self.assertLess(abs((p.coordinate-coordinate+.5)%1-.5),2e-6)
    def test_stage_update_changes_profile_without_geometry_jump(self):
        b=bank();b.set_stage(1,0);b.acquire(.32,.01,-1);p=b.make('rotation_reverse',.123,2);b.items=[p];b.active=p.key;before=p.coordinate
        b.set_stage(2,.02);self.assertLess(abs((p.coordinate-before+.5)%1-.5),2e-6)
        self.assertEqual(b.last_stage_change['from_stage'],2)
    def test_forward_profile_has_correct_positive_derivatives(self):
        b=bank();b.set_stage(4,0);p=b.make('rotation_forward',.6,2);self.assertIsNotNone(p.warp)
        phase=p.phase;h=1e-5;velocity=p.coordinate_velocity;p.phase=phase+p.speed*h;future=p.coordinate;p.phase=phase-p.speed*h;past=p.coordinate
        self.assertAlmostEqual((future-past)/(2*h),velocity,places=4)
        self.assertGreater(velocity,0)
    def test_independent_fit_can_find_speed_above_old_highest_slot(self):
        rng=np.random.default_rng(17);times=np.cumsum(rng.uniform(.035,.065,65));times-=times[0];grid=np.arange(96)/96;rate=1.9;phase=(.4140625+rate*times+.21)%1
        records=[]
        for t,x in zip(times,phase):
            gap=(grid-x+.5)%1-.5;q=np.exp(-.5*(gap/.025)**2)
            records.append(dict(time=float(t),quality=q.tolist()))
        result=fit(records,.4140625,1);self.assertAlmostEqual(result['rate'],rate,delta=.02)

    def test_unmeasured_deceleration_cannot_take_over_in_diagnostic_policy(self):
        b=bank();b.c['uncalibrated_decelerate_diagnostic_only']=True;b.set_stage(2,0);b.acquire(.2,.01,-1);a=next(p for p in b.items if p.key==b.active)
        p=b.make('rotation_reverse',a.phase,0,parent=a.key);p.visual=True;p.score=1.
        self.assertFalse(b.legal_successor(a,p,.02))
    def test_exit_candidates_keep_direction_profile_geometry_aligned(self):
        b=bank();b.set_stage(2,0);b.acquire(.2,.01,-1);a=b.make('low_swing',.2,0,1);b.items=[a];b.active=a.key;b.low_entry_direction=1;b.low_played_cycles=1.2;b.low_turns={-1,1}
        p=b.reconstruct_exit(.25,.9475,.02,clock_rate=True)
        self.assertIsNotNone(p);children=[p for p in b.items if p.mode=='rotation_reverse']
        self.assertTrue(all(abs((p.coordinate-.25+.5)%1-.5)<2e-6 for p in children))


class TemporalContrastTests(unittest.TestCase):
    def test_fixed_spatial_bias_is_removed_without_changing_dynamic_evidence(self):
        t=np.arange(60);g=np.arange(96)/96
        phase=(t*.017)%1;gap=(g[None,:]-phase[:,None]+.5)%1-.5
        moving=np.exp(-.5*(gap/.02)**2)
        fixed=2*np.exp(-.5*((g-.45)/.07)**2)
        np.testing.assert_allclose(temporal_contrast(moving+fixed),temporal_contrast(moving),atol=1e-12)
