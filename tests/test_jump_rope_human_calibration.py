import json
from pathlib import Path
import unittest
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank
ROOT=Path(__file__).resolve().parents[1]
def config():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_human_calibration_config.json').read_text())
def profiles():return json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/stage_profiles_v1.json').read_text())

class HumanCalibrationTests(unittest.TestCase):
    def test_low_stage_upgrades_do_not_replace_circle_gears(self):
        b=StagedTrajectoryBank(config(),.7,.4,profiles());gears=b.c['rotation_gears'];old=b.c['swing_gears'][0]
        b.set_stage(2,0);self.assertEqual(b.c['rotation_gears'],gears);self.assertGreater(b.c['swing_gears'][0],old)
        self.assertAlmostEqual(b.c['swing_gears'][0],.49880574854534915)
        p=b.make('rotation_reverse',.3,3);self.assertEqual(b.role(p),'rotation_slot_3')
    def test_reset_uses_g_initial_rate_not_stage_role_index(self):
        b=StagedTrajectoryBank(config(),.7,.4,profiles());b.set_stage(3,0);b.reset();b.acquire(.2,.1)
        self.assertEqual(next(p for p in b.items if p.key==b.active).gear,0)
    def test_circle_playback_speed_and_phase_preserved_by_low_only_upgrade(self):
        b=StagedTrajectoryBank(config(),.7,.4,profiles());b.acquire(.2,0);p=next(p for p in b.items if p.key==b.active);before=(p.phase,p.speed)
        b.set_stage(2,.01);self.assertEqual((p.phase,p.speed),before)
    def test_alternating_winners_do_not_restart_speed_confirmation(self):
        c=config();c['window_branch_confirmation']=True;c['window_branch_modes']=['rotation_forward','rotation_reverse'];b=LandingTrajectoryBank(c,.7,.4);b.acquire(.69,0);b.advance(.04)
        active=next(p for p in b.items if p.key==b.active);candidates=[p for p in b.items if p.key in b.branch_info and p.mode==active.mode and p.gear in (1,2)]
        chosen=active
        for i in range(7):
            now=.04+i*.02
            if i:b.advance(now)
            active.visual=True;active.score=.15;b.record_evidence(active,.15,.8,.2)
            for j,p in enumerate(candidates):p.visual=True;p.score=.90 if i%2==j else .89;b.record_evidence(p,.85 if j==0 else .8,.8,.2)
            chosen=b.choose(now,.02)
            if chosen.key!=active.key:break
        self.assertEqual(chosen.key,candidates[0].key);self.assertEqual(b.branch_adoptions,1)
    def test_single_clear_frame_cannot_override_playback(self):
        b=LandingTrajectoryBank(config(),.7,.4);b.acquire(.69,0);b.advance(.04);active=next(p for p in b.items if p.key==b.active);candidate=next(p for p in b.items if p.key in b.branch_info and p.gear==2)
        active.visual=candidate.visual=True;active.score=.1;candidate.score=.9;b.record_evidence(active,.1,.9,.2);b.record_evidence(candidate,.9,.9,.2)
        self.assertEqual(b.choose(.04,.02).key,active.key)
    def test_human_labels_preserve_missing_stage_and_mixed_direction(self):
        labels=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_samples/human/20261005-five-frames.json').read_text())
        self.assertEqual(len(labels['annotations']),5);self.assertEqual(labels['annotations'][1]['truth'],'正摇');self.assertEqual(labels['annotations'][2]['truth'],'反摇')
        self.assertTrue(all(a['stage']=='' for a in labels['annotations']))


class LegacyCandidateTests(unittest.TestCase):
    def test_unselectable_old_candidates_expire_but_active_survives(self):
        b=LandingTrajectoryBank(config(),.7,.4);b.acquire(.2,0);key=b.active;b.advance(1.)
        self.assertEqual([p.key for p in b.items],[key])
    def test_optional_quarter_cycle_bound_rejects_half_cycle_alias(self):
        c=config();c["branch_max_clock_gap"]=.25
        b=LandingTrajectoryBank(c,.7,.4);b.acquire(.69,0);b.advance(.04);a=next(p for p in b.items if p.key==b.active);p=next(p for p in b.items if p.key in b.branch_info and p.key!=a.key)
        p.phase=a.phase+.45;p.visual=True
        for i in range(8):
            b.time=.04+i*.02;b.record_evidence(a,.1,.9,.2);b.record_evidence(p,.9,.9,.2)
        self.assertFalse(b.supported_branch(a,p,b.time))
