import json
from pathlib import Path
import unittest
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank

ROOT=Path(__file__).resolve().parents[1]

def settings():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear_config.json').read_text(encoding='utf-8'))

class LandingBranchTests(unittest.TestCase):
    def bank(self):return LandingTrajectoryBank(settings(),.7,.4)
    def test_every_landing_preserves_all_rotation_gears_including_current(self):
        bank=self.bank();bank.acquire(.69,0);key=bank.active;bank.advance(.04)
        fresh=[p for p in bank.items if p.key in bank.branch_info and p.mode=='rotation_forward']
        self.assertEqual({p.gear for p in fresh},set(range(4)))
        self.assertEqual(len(fresh),4);self.assertTrue(any(p.key==key for p in bank.items))
        self.assertTrue(all(p.parent==key for p in fresh))
    def test_fresh_landing_branch_is_not_merged_with_stale_same_gear(self):
        bank=self.bank();bank.acquire(.69,0);stale=bank.items[-1];stale.score=.99
        bank.advance(.04)
        self.assertTrue(any(p.key==stale.key for p in bank.items))
        self.assertTrue(any(p.gear==stale.gear and p.key in bank.branch_info for p in bank.items))
    def test_unobserved_candidates_keep_distinct_fixed_speed_predictions(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04)
        fresh=[p for p in bank.items if p.key in bank.branch_info and p.mode=='rotation_forward']
        phases={p.key:p.phase for p in fresh};speeds={p.key:p.speed for p in fresh}
        bank.advance(.10)
        for p in fresh:
            p.visual=True;bank.correct(p,-.1,.06,.9,.5)
            self.assertAlmostEqual(p.phase,phases[p.key]+speeds[p.key]*.06)
            self.assertEqual(p.speed,speeds[p.key])
    def test_single_lucky_frame_does_not_confirm_branch(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04);active=next(p for p in bank.items if p.key==bank.active)
        candidate=next(p for p in bank.items if p.key in bank.branch_info and p.mode==active.mode and p.gear==3)
        active.visual=candidate.visual=True;bank.record_evidence(active,.2,.5,.1);bank.record_evidence(candidate,.95,.9,.2)
        self.assertFalse(bank.legal_successor(active,candidate,.04))
    def test_multi_frame_confirmation_adopts_played_phase_without_old_clock_clamp(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04);active=next(p for p in bank.items if p.key==bank.active)
        candidate=next(p for p in bank.items if p.key in bank.branch_info and p.mode==active.mode and p.gear==3)
        for i in range(10):
            now=.04+i*.02
            if i:bank.advance(now)
            active.visual=candidate.visual=True;active.score=.2;candidate.score=.95
            bank.record_evidence(active,.2,.5,.1);bank.record_evidence(candidate,.95,.9,.2)
            predicted=candidate.phase;chosen=bank.choose(now,.02)
            if chosen.key==candidate.key:
                self.assertAlmostEqual(chosen.phase,predicted);self.assertGreater(abs(chosen.phase-active.phase),.008)
                self.assertEqual(bank.branch_adoptions,1);break
        else:self.fail('supported branch did not take over')
    def test_unconfirmed_low_branch_cannot_create_reverse_descendants(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04)
        for i in range(1,50):bank.advance(.04+i*.02)
        self.assertFalse(any(p.mode=='rotation_reverse' for p in bank.items))
        self.assertLessEqual(len(bank.items),settings()['max_hypotheses'])
    def test_nonmonotonic_and_invalid_branch_settings_rejected(self):
        bank=self.bank();bank.acquire(.3,0)
        with self.assertRaises(ValueError):bank.advance(-1)
        for name,value in [('branch_evidence_frames',1),('branch_lifetime',float('nan'))]:
            c=settings();c[name]=value
            with self.assertRaises(ValueError):LandingTrajectoryBank(c,.7,.4)

    def test_confirmed_landing_discards_older_gear_branches(self):
        bank=self.bank();bank.acquire(.69,0);bank.advance(.04)
        active=next(p for p in bank.items if p.key==bank.active)
        candidate=next(p for p in bank.items if p.key in bank.branch_info and p.mode==active.mode and p.gear==3)
        others=[p for p in bank.items if p.key in bank.branch_info and p.key!=candidate.key]
        bank.resolved_landing=bank.branch_info[candidate.key]['landing'];bank.active=candidate.key;bank.prune()
        self.assertTrue(all(p.key!=old.key for old in others for p in bank.items))
        for old in others:self.assertFalse(bank.supported_branch(candidate,old,.04))

    def test_explicit_baseline_settings_keep_original_bank(self):
        from modular_agent.realtime import jump_rope
        from modular_agent.realtime.trajectory_bank import TrajectoryBank
        c,m,_=jump_rope.load(ROOT)
        path='docs/jump-rope/history/gear-v4-before-landing-branches/domains/hololive_dreams/models/jump_rope_phase_gear_config.json'
        vision,_=jump_rope.phase_rope_components(ROOT,c,m,gear=True,gear_settings_path=path)
        self.assertIs(type(vision.bank),TrajectoryBank)

    def test_cli_settings_without_gear_rejected_before_input(self):
        from unittest.mock import patch
        from modular_agent.realtime import jump_rope
        with patch('sys.argv',['jump_rope','--gear-settings','anything']),patch.object(jump_rope,'ActionComputer') as computer:
            with self.assertRaises(SystemExit):jump_rope.main()
            computer.assert_not_called()


class ExitSpeedTests(unittest.TestCase):
    def test_direction_confirmation_keeps_exit_speeds_eligible_before_next_landing(self):
        c=settings();c['exit_speed_branches']=True;b=LandingTrajectoryBank(c,.7,.4)
        b.time=1.;low=b.make('low_swing',.4,0,1);b.items=[low];b.active=low.key;b.low_entry_direction=1;b.low_played_cycles=1.2;b.landing_number=5
        slow=b.make('rotation_reverse',.3,0,-1,parent=low.key);fast=b.make('rotation_reverse',.3,1,-1,parent=low.key);b.items.extend([slow,fast])
        b.commit_episode(low,slow);b.active=slow.key
        self.assertEqual(b.landing_number,6);self.assertIn(fast.key,b.branch_info)
        for i in range(12):
            now=1.+i*.02
            if i:b.advance(now)
            slow.visual=fast.visual=True;slow.score=.15;fast.score=.9
            b.record_evidence(slow,.15,.7,.2);b.record_evidence(fast,.9,.7,.2)
            selected=b.choose(now,.02)
            if selected.key==fast.key:break
        self.assertEqual(selected.key,fast.key)
        self.assertEqual(b.landing_number,6)
    def test_exit_candidate_does_not_drift_to_slower_bound_before_confirmation(self):
        c=settings();c['exit_speed_branches']=True;b=LandingTrajectoryBank(c,.7,.4)
        low=b.make('low_swing',.4,0);b.items=[low];b.active=low.key
        p=b.make('rotation_reverse',.3,0,-1,parent=low.key);p.visual=True;before=(p.phase,p.speed)
        b.correct(p,.04,.02,.9,.3);self.assertEqual((p.phase,p.speed),before)


class RotationRateAssistTests(unittest.TestCase):
    def test_coherent_hint_overrides_noise_within_gear_bounds_and_expires(self):
        c=settings();c['rotation_rate_assist']=True;b=LandingTrajectoryBank(c,.7,.4);b.acquire(.3,1,-1)
        p=next(p for p in b.items if p.key==b.active);p.visual=True;b.rate_hint=dict(rate=.76,time=1.);b.rate_hint_mode=p.mode
        b.correct(p,.01,.02,.8,.3);self.assertGreater(p.speed,.74)
        b.rate_hint['rate']=3.;b.correct(p,.01,.02,.8,.3);self.assertLessEqual(p.speed,b.bounds(p)[1])
        b.time=2.;old=p.speed;b.correct(p,0.,.02,.8,.3);self.assertEqual(p.speed,old)
