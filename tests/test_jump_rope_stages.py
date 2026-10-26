import json
from pathlib import Path
import unittest
import numpy as np
from modular_agent.realtime.stage_badge import StageBadge
from modular_agent.realtime.staged_trajectory_bank import StagedTrajectoryBank
from modular_agent.realtime import jump_rope

ROOT=Path(__file__).resolve().parents[1]

def config():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_stage_config.json').read_text(encoding='utf-8'))
def profiles():return json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/stage_profiles_v1.json').read_text(encoding='utf-8'))

class StageBankTests(unittest.TestCase):
    def bank(self):return StagedTrajectoryBank(config(),.7,.4,profiles())
    def test_each_stage_has_four_roles_and_all_speeds_increase(self):
        p=profiles()['stages'];roles={'normal','accelerate','decelerate','low_swing'}
        self.assertTrue(all(set(s['branches'])==roles for s in p))
        for role in roles:self.assertTrue(all(b['branches'][role]['clock_rate']>a['branches'][role]['clock_rate'] for a,b in zip(p,p[1:])))
    def test_global_upgrade_preserves_phase_direction_and_low_episode(self):
        bank=self.bank();p=bank.make('low_swing',.8,0,-1);bank.items=[p];bank.active=p.key;bank.time=1;bank.low_episode=2;bank.low_entry_direction=-1
        phase=p.phase;old=p.speed;bank.set_stage(2,1.01)
        self.assertEqual(p.phase,phase);self.assertGreater(p.speed,old)
        self.assertEqual(bank.low_episode,2);self.assertEqual(bank.low_entry_direction,-1)
        bank.advance(1.02);self.assertGreater(p.phase,phase)
    def test_initial_acquisition_uses_stage_normal_and_landing_branches_use_three_circle_roles(self):
        bank=self.bank();bank.acquire(.69,0);p=next(p for p in bank.items if p.key==bank.active)
        self.assertEqual(bank.role(p),'normal');bank.advance(.04)
        self.assertEqual({bank.role(p) for p in bank.items if p.key in bank.branch_info},{'normal','accelerate','decelerate'})
    def test_upgrade_discards_old_speed_evidence_but_not_active_track(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04);key=bank.active
        bank.pending=('x',);bank.evidence={key:[(.04,.9,True)]};bank.set_stage(1,.05)
        self.assertEqual(bank.active,key);self.assertEqual(len(bank.items),1);self.assertFalse(bank.branch_info);self.assertFalse(bank.evidence);self.assertIsNone(bank.pending)
        self.assertFalse(bank.set_stage(0,.06))
    def test_reset_restores_first_stage_rates(self):
        bank=self.bank();rates=bank.rates(0);bank.set_stage(4,0);bank.reset()
        self.assertEqual(bank.stage_index,0);self.assertEqual(bank.c['rotation_gears'],rates['rotation_gears'])
    def test_invalid_or_stale_stage_hint_rejected(self):
        bank=self.bank();bank.acquire(.3,1)
        for stage,time in [(True,1),(9,1),(1,.5),(1,float('nan'))]:
            with self.assertRaises(ValueError):bank.set_stage(stage,time)
    def test_real_factory_exposes_stage_and_stays_judgment_only_on_blank_frames(self):
        c,m,_=jump_rope.load(ROOT);v,controller=jump_rope.phase_rope_components(ROOT,c,m,gear=True,gear_settings_path='domains/hololive_dreams/models/jump_rope/jump_rope_stage_config.json')
        for i in range(10):o=v.detect(np.zeros((180,320,3),np.uint8),i*.02)
        self.assertEqual(o['difficulty_stage'],1);self.assertFalse(o['rope_valid']);self.assertGreater(o['phase_estimate']['clock_rate'],0)
        self.assertFalse(controller(c).step(o,.2,False)['down'])

class StageCueTests(unittest.TestCase):
    def cue(self):return StageBadge(dict(roi=[0,0,1,1],histograms=np.eye(18)[:5].tolist()),[0,0,1,1])
    def test_infrequent_multisample_confirmation_and_no_regression(self):
        cue=self.cue();cue.vector=lambda image:np.eye(18)[2]
        self.assertIsNone(cue.update(None,0));self.assertIsNone(cue.update(None,.02));self.assertEqual(cue.update(None,.11),2)
        cue.vector=lambda image:np.eye(18)[1]
        self.assertIsNone(cue.update(None,.22));self.assertEqual(cue.stage,2)
    def test_occlusion_and_ambiguous_cue_do_not_upgrade(self):
        cue=self.cue();cue.vector=lambda image:None
        self.assertIsNone(cue.update(None,0));cue.vector=lambda image:(np.eye(18)[0]+np.eye(18)[1])/np.sqrt(2)
        self.assertIsNone(cue.update(None,.2));self.assertIsNone(cue.stage)
    def test_bad_roi_rejected_instead_of_reading_wrong_crop(self):
        with self.assertRaises(ValueError):StageBadge(dict(roi=[0,0,.2,.2],histograms=np.eye(18)[:5].tolist()),[.3,.3,1,1])


class InitialStageRuleTests(unittest.TestCase):
    def test_only_confirmed_initial_stage_forbids_reverse(self):
        c=config();c['initial_stage_forward_only']=True;b=StagedTrajectoryBank(c,.7,.4,profiles())
        b.acquire(.4,0,-1);self.assertEqual(next(p for p in b.items if p.key==b.active).mode,'rotation_reverse')
        b.reset();b.set_stage(0,0);b.acquire(.4,.1,-1)
        self.assertEqual(next(p for p in b.items if p.key==b.active).mode,'rotation_forward')
        b.reset();b.set_stage(1,0);b.acquire(.4,.1,-1)
        self.assertEqual(next(p for p in b.items if p.key==b.active).mode,'rotation_reverse')
