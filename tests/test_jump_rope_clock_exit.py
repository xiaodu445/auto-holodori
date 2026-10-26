import json
from pathlib import Path
import unittest
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
ROOT=Path(__file__).resolve().parents[1]
def config():
    return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_clock_exit_config.json').read_text())
def low_bank():
    b=LandingTrajectoryBank(config(),.4140625,.4);b.acquire(.2,0)
    p=b.make('low_swing',1.2,0,-1);b.items=[p];b.active=p.key
    b.low_entry_direction=-1;b.low_played_cycles=1.2;b.low_turns={-1,1}
    return b,p
class ClockExitTests(unittest.TestCase):
    def test_duplicate_frames_do_not_erase_supported_exit_window(self):
        b,a=low_bank();p=b.make('rotation_forward',.8,1,1,parent=a.key);p.exit_supported=True;b.items.append(p)
        for i in range(11):
            b.time=.02*i;p.visual=i%2==0;p.score=.8;a.visual=False;a.score=.05
            b.record_evidence(a,.05,0,0);b.record_evidence(p,.8 if p.visual else .05,.9,.5 if p.visual else 0)
            b.choose(b.time,.02)
            if b.active==p.key:break
        self.assertEqual(b.active,p.key);self.assertEqual(b.mode_switches,1);self.assertEqual(b.direction_changes,1)
        self.assertEqual(b.low_episode,0);self.assertFalse(b.rotation_rearmed)
    def test_one_clear_frame_cannot_commit_exit(self):
        b,a=low_bank();p=b.make('rotation_forward',.8,1,1,parent=a.key);p.visual=True;p.score=.8;p.exit_supported=True;b.items.append(p)
        b.time=.1;b.record_evidence(a,.05,0,0);b.record_evidence(p,.8,.9,.5);b.choose(.1,.02)
        self.assertEqual(b.active,a.key)
    def test_wrong_direction_cannot_commit_even_with_strong_window(self):
        b,a=low_bank();p=b.make('rotation_reverse',.8,1,-1,parent=a.key);p.visual=True;p.score=.8;p.exit_supported=True;b.items.append(p)
        for i in range(11):
            b.time=.02*i;b.record_evidence(a,.05,0,0);b.record_evidence(p,.8,.9,.5);b.choose(b.time,.02)
        self.assertEqual(b.active,a.key)
    def test_reverse_exit_clock_rate_not_divided_by_local_warp_twice(self):
        b,a=low_bank();b.low_entry_direction=1;a.origin=1
        p=b.reconstruct_exit(.25,.735,.2,clock_rate=True)
        self.assertIsNotNone(p);self.assertAlmostEqual(p.speed,.735);self.assertAlmostEqual(p.coordinate,.25,places=5)

    def test_reverse_exit_seeds_competing_gears_without_teleporting_active(self):
        b,a=low_bank();b.low_entry_direction=1;a.origin=1
        p=b.reconstruct_exit(.25,.9475,.2,clock_rate=True)
        children=[p for p in b.items if p.mode=='rotation_reverse']
        self.assertEqual(len(children),4);self.assertEqual(b.active,a.key)
        self.assertTrue(all(abs(p.coordinate-.25)<1e-5 and p.speed>0 for p in children))
        self.assertIsNone(b.reconstruct_exit(.24,.9475,.22,clock_rate=True))
    def test_observed_rotation_recovery_retains_direction_until_confirmation(self):
        b=LandingTrajectoryBank(config(),.4140625,.4);b.acquire(.2,0,-1);old=b.active
        self.assertTrue(b.recover_rotation(.15,.02));self.assertEqual(b.active,old)
        self.assertTrue(all(p.mode=='rotation_reverse' for p in b.items))
        self.assertFalse(b.recover_rotation(.14,.03))
    def test_stage_low_speed_update_preserves_unchanged_circle_evidence(self):
        from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank
        profiles=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/stage_profiles_v1.json').read_text())
        b=StagedTrajectoryBank(config(),.4140625,.4,profiles);b.acquire(.4,0,-1);b.advance(.04)
        candidate=next(p for p in b.items if p.key!=b.active and p.mode=='rotation_reverse')
        b.record_evidence(candidate,.8,.9,.5);record=list(b.evidence[candidate.key]);speed=candidate.speed
        b.set_stage(2,.04)
        self.assertIn(candidate,b.items);self.assertEqual(list(b.evidence[candidate.key]),record);self.assertEqual(candidate.speed,speed)
