import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.realtime.trajectory_bank import TrajectoryBank,AngularWarp
from modular_agent.realtime import jump_rope

ROOT=Path(__file__).resolve().parents[1]
def settings():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_phase_gear_config.json').read_text(encoding='utf-8'))

class PlaybackTests(unittest.TestCase):
    def bank(self):return TrajectoryBank(settings(),.7,.4)

    def test_rotation_coasts_first_frame_both_directions_and_never_zero(self):
        for direction in (-1,1):
            bank=self.bank();bank.acquire(.3,0,direction)
            p=next(p for p in bank.items if p.key==bank.active);old=p.phase;rate=p.speed
            bank.advance(.02)
            self.assertAlmostEqual(p.phase,old+direction*rate*.02)
            for i in range(2,500):
                bank.advance(i*.02);bank.choose(i*.02,.02)
                self.assertTrue(all(p.speed>0 for p in bank.items))
                self.assertLessEqual(len(bank.items),settings()['max_hypotheses'])

    def test_no_state_or_gear_branches_away_from_boundary(self):
        bank=self.bank();bank.acquire(.2,0);initial={p.key for p in bank.items}
        bank.advance(.04)
        self.assertEqual({p.key for p in bank.items},initial)
        self.assertTrue(all(p.mode=='rotation_forward' for p in bank.items))

    def test_ground_crossing_creates_swing_and_preserves_parent(self):
        bank=self.bank();bank.acquire(.69,0);key=bank.active
        bank.advance(.04)
        self.assertTrue(any(p.mode=='low_swing' for p in bank.items))
        self.assertTrue(any(p.key==key for p in bank.items))
        self.assertFalse(any(p.mode=='rotation_reverse' for p in bank.items))

    def test_swing_exit_has_opposite_rotation_direction(self):
        for origin in (-1,1):
            bank=self.bank();p=bank.make('low_swing',bank.swing_entry-.01,0,origin);bank.items=[p];bank.active=p.key;bank.time=0;bank.low_turns={-1,1};bank.low_entry_direction=origin
            bank.advance(.04)
            expected='rotation_reverse' if origin>0 else 'rotation_forward'
            self.assertTrue(any(p.mode==expected for p in bank.items))
            self.assertFalse(any(p.mode==('rotation_forward' if origin>0 else 'rotation_reverse') for p in bank.items))

    def test_small_correction_cannot_reverse_or_cancel_travel(self):
        for direction in (-1,1):
            bank=self.bank();bank.acquire(.3,0,direction);p=next(p for p in bank.items if p.key==bank.active)
            old=p.phase;bank.advance(.02);p.visual=True
            bank.correct(p,-direction*10,.02,.9,.3)
            self.assertGreater(direction*(p.phase-old),0)
            lo,hi=bank.bounds(p)
            for i in range(1000):bank.correct(p,10 if i%2 else -10,.02,.9,.3)
            self.assertTrue(lo<=p.speed<=hi)

    def test_occlusion_rearm_requires_played_cycle_and_real_upper_support(self):
        config=settings();config['occlusion_tolerant_rearm']=True
        bank=TrajectoryBank(config,.7,.4);bank.acquire(.3,0);bank.rotation_rearmed=False
        for i in range(1,101):bank.advance(i*.02);bank.choose(i*.02,.02)
        self.assertGreater(bank.rearm_played_cycles,1);self.assertFalse(bank.rotation_rearmed)
        for i in range(101,111):
            bank.advance(i*.02);p=next(p for p in bank.items if p.key==bank.active);p.upper_supported=True
            bank.choose(i*.02,.02)
        self.assertTrue(bank.rotation_rearmed);self.assertGreaterEqual(bank.rearm_upper_travel,.08)

    def test_one_upper_sample_does_not_rearm(self):
        config=settings();config['occlusion_tolerant_rearm']=True
        bank=TrajectoryBank(config,.7,.4);bank.acquire(.3,0);bank.rotation_rearmed=False
        bank.advance(2);p=next(p for p in bank.items if p.key==bank.active);p.upper_supported=True
        bank.choose(2,2);self.assertFalse(bank.rotation_rearmed)
        bank.advance(2.02);bank.choose(2.02,.02);self.assertFalse(bank.rotation_rearmed)

    def test_unconfirmed_template_is_not_corrected_when_frozen(self):
        config=settings();config['freeze_unconfirmed_correction']=True
        bank=TrajectoryBank(config,.7,.4);bank.acquire(.3,0);bank.advance(.02)
        child=next(p for p in bank.items if p.key!=bank.active);child.visual=True
        before=(child.phase,child.speed);bank.correct(child,.03,.02,.9,.3)
        self.assertEqual(before,(child.phase,child.speed))
        active=next(p for p in bank.items if p.key==bank.active);active.visual=True;before=active.phase
        bank.correct(active,.03,.02,.9,.3);self.assertGreater(active.phase,before)

    def test_rate_adaptation_step_and_zero_gain(self):
        config=settings();config.update(rate_adaptation_gain=.002,rate_step_limit=.0005)
        bank=TrajectoryBank(config,.7,.4);bank.acquire(.3,0);p=bank.items[0];p.visual=True
        old=p.speed;bank.correct(p,1.,.02,.9,.3)
        self.assertAlmostEqual(p.speed-old,.0005)
        bank.c['rate_adaptation_gain']=0;old=p.speed;phase=p.phase
        bank.correct(p,.03,.02,.9,.3)
        self.assertEqual(p.speed,old);self.assertGreater(p.phase,phase)

    def test_invalid_optional_adaptation_rejected(self):
        for name,value in [('freeze_unconfirmed_correction','false'),('rate_adaptation_gain',-1),('rate_step_limit',float('nan'))]:
            config=settings();config[name]=value
            with self.assertRaises(ValueError):TrajectoryBank(config,.7,.4)

    def test_missing_observation_does_not_change_speed(self):
        bank=self.bank();bank.acquire(.3,0);p=bank.items[0];speed=p.speed
        bank.correct(p,10,.02,.9,.3)
        self.assertEqual(p.speed,speed)

    def test_swing_clock_keeps_advancing_at_zero_projection_velocity(self):
        bank=self.bank();p=bank.make('low_swing',bank.warp.inverse(.5),0);bank.items=[p];bank.active=p.key;bank.time=0
        self.assertAlmostEqual(math.sin(2*math.pi*p.angle),0)
        bank.advance(.02)
        self.assertGreater(p.phase,bank.warp.inverse(.5));self.assertLess(p.coordinate,1);self.assertGreater(p.speed,0)

    def test_swing_turn_zero_velocity_has_nonzero_returning_acceleration(self):
        bank=self.bank()
        for phase,sign in ((0.,1),(.5,-1)):
            p=bank.make('low_swing',bank.warp.inverse(phase),0)
            self.assertAlmostEqual(p.coordinate_velocity,0.,places=10)
            self.assertGreater(sign*p.template_acceleration,0.)
            bank.items=[p];bank.active=p.key;bank.time=0.;bank.advance(.02)
            self.assertGreater(sign*p.coordinate_velocity,0.)

    def test_one_frame_challenger_cannot_change_active_model(self):
        bank=self.bank();bank.acquire(.3,0);active=bank.active
        other=next(p for p in bank.items if p.key!=active);other.score=.9;other.visual=True
        bank.choose(.02,.02);self.assertEqual(bank.active,active)
        other.visual=False;bank.choose(.04,.02);self.assertEqual(bank.active,active)

    def test_model_selection_cannot_make_large_same_path_phase_jump(self):
        bank=self.bank();bank.acquire(.3,0);key=bank.active
        other=next(p for p in bank.items if p.key!=key);other.phase+=.10;other.score=.9;other.visual=True
        bank.choose(.02,.02);bank.choose(.2,.02)
        self.assertEqual(bank.active,key)

    def test_geometry_callback_can_reject_incompatible_state_transition(self):
        bank=self.bank();bank.acquire(.3,0);key=bank.active
        other=bank.make('low_swing',.4,0,score=.9,parent=key);other.visual=True;bank.items.append(other)
        bank.choose(.02,.02,lambda a,b:False);bank.choose(.2,.02,lambda a,b:False)
        self.assertEqual(bank.active,key)

    def test_unconfirmed_swing_cannot_spawn_reverse_descendant(self):
        bank=self.bank();bank.acquire(.2,0)
        pending=bank.make('low_swing',.39,0,parent=bank.active);bank.items.append(pending)
        bank.low_turns={-1,1};bank.advance(.04)
        self.assertFalse(any(p.mode=='rotation_reverse' for p in bank.items))

    def test_confirmed_episode_discards_stale_rotation_branches(self):
        bank=self.bank();bank.acquire(.2,0);old=list(bank.items);key=bank.active
        swing=bank.make('low_swing',.4,0,score=.95,parent=key);swing.visual=True;bank.items.append(swing)
        bank.choose(.02,.02);bank.choose(.1,.02)
        self.assertEqual(bank.low_entry_direction,1);self.assertEqual(bank.low_episode,1)
        self.assertTrue(all(p.mode=='low_swing' for p in bank.items))
        for ghost in old:self.assertFalse(bank.legal_successor(swing,ghost,.11))
        wrong=bank.make('low_swing',swing.phase,0,origin=-1,score=.99);wrong.visual=True;bank.items.append(wrong)
        bank.choose(.12,.02);bank.choose(.22,.02)
        self.assertEqual(bank.active,swing.key);self.assertEqual(bank.low_entry_direction,1)

    def test_exit_reverses_once_and_requires_visible_normal_cycle_before_reentry(self):
        bank=self.bank();swing=bank.make('low_swing',.6,0,origin=1);bank.items=[swing];bank.active=swing.key;bank.time=0
        bank.low_entry_direction=1;bank.low_turns={-1,1}
        exit_model=bank.make('rotation_reverse',.7,1,origin=-1,score=.99,parent=swing.key);exit_model.visual=True;bank.items.append(exit_model)
        bank.choose(.02,.02);bank.choose(.1,.02)
        self.assertEqual(bank.active,exit_model.key);self.assertEqual(bank.direction_changes,1)
        self.assertFalse(bank.rotation_rearmed)
        low=bank.make('low_swing',.4,0,origin=-1,score=1.,parent=exit_model.key)
        self.assertFalse(bank.legal_successor(exit_model,low,.2))
        exit_model.turn_supported=True;bank.choose(.12,.02)
        for i in range(1,52):
            exit_model.phase-=.02;exit_model.turn_supported=True;bank.choose(.12+i*.02,.02)
        self.assertTrue(bank.rotation_rearmed)
        self.assertEqual(bank.direction_changes,1)

    def test_one_visible_endpoint_does_not_finish_swing_episode(self):
        bank=self.bank();swing=bank.make('low_swing',.39,0);bank.items=[swing];bank.active=swing.key;bank.time=0
        bank.low_entry_direction=1;bank.low_turns={1};bank.advance(.04)
        self.assertFalse(any(p.mode=='rotation_reverse' for p in bank.items))

    def test_recent_ground_speed_branch_switch_is_clamped_to_small_phase_step(self):
        bank=self.bank();bank.acquire(.3,0);active=next(p for p in bank.items if p.key==bank.active)
        child=bank.make(active.mode,.35,len(bank.gears(active.mode))-1,score=.99,parent=active.key);child.visual=True;bank.items.append(child)
        bank.choose(.02,.02);bank.choose(.1,.02)
        self.assertEqual(bank.active,child.key)
        self.assertLessEqual(abs(child.phase-active.phase),settings()['max_phase_correction']+1e-9)
        self.assertGreater(child.speed,active.speed)

    def test_missing_endpoint_exit_needs_full_playback_and_strong_persistent_normal_evidence(self):
        bank=self.bank();low=bank.make('low_swing',.5,0);bank.items=[low];bank.active=low.key;bank.time=0
        bank.low_entry_direction=1;bank.low_played_cycles=1.1
        exit_model=bank.make('rotation_reverse',.7,0,origin=-1,score=.99,parent=low.key);exit_model.visual=True;bank.items.append(exit_model)
        self.assertFalse(bank.legal_successor(low,exit_model,.02))
        exit_model.exit_supported=True
        bank.choose(.02,.02);bank.choose(.12,.02)
        self.assertEqual(bank.active,low.key)
        bank.choose(.25,.02)
        self.assertEqual(bank.active,exit_model.key);self.assertEqual(bank.direction_changes,1)

    def test_reconstructed_exit_keeps_frozen_direction_and_is_not_new_episode(self):
        bank=self.bank();low=bank.make('low_swing',.5,0,origin=-1);bank.items=[low];bank.active=low.key;bank.time=4.
        bank.low_entry_direction=-1;bank.low_episode=1;bank.low_played_cycles=1.2
        candidate=bank.reconstruct_exit(.8,1.43,4.)
        self.assertEqual(candidate.mode,'rotation_forward');self.assertTrue(candidate.recovered_exit)
        candidate.visual=True;candidate.score=.99
        bank.choose(4.02,.02);bank.choose(4.25,.02)
        self.assertEqual(bank.low_episode,1);self.assertEqual(bank.direction_changes,1)
        self.assertTrue(bank.last_exit_recovered)
        self.assertTrue(all(p.mode=='rotation_forward' for p in bank.items))

    def test_invalid_gear_and_correction_settings_rejected(self):
        for key,value in [('rotation_gears',[0,.4]),('swing_gears',[.5,.4]),('gear_tolerance',.8),('max_phase_correction',.1)]:
            c=settings();c[key]=value
            with self.assertRaises(ValueError):TrajectoryBank(c,.7,.4)

    def test_nonmonotonic_time_rejected(self):
        bank=self.bank();bank.acquire(.2,0)
        for now in (0,-1,float('nan')):
            with self.assertRaises(ValueError):bank.advance(now)

class TimeProfileTests(unittest.TestCase):
    def test_monotone_profile_and_periodic_first_derivative(self):
        warp=AngularWarp(settings()['swing_time_profile'])
        values=[warp.evaluate(t) for t in np.linspace(0,1,1001,endpoint=False)]
        self.assertTrue(all(x[1]>0 for x in values))
        self.assertTrue(all(b[0]>a[0] for a,b in zip(values,values[1:])))
        self.assertAlmostEqual(warp.evaluate(0)[1],warp.evaluate(1-1e-10)[1],places=6)
        for phi in (.1,.3,.5,.8):self.assertAlmostEqual(warp.evaluate(warp.inverse(phi))[0],phi,places=10)

    def test_knot_coordinate_velocity_is_continuous(self):
        bank=TrajectoryBank(settings(),.7,.4)
        for clock in bank.warp.x[1:-1]:
            p=bank.make('low_swing',clock-1e-9,0);left=p.coordinate_velocity
            p.phase=clock+1e-9
            self.assertAlmostEqual(left,p.coordinate_velocity,places=6)

    def test_invalid_flat_or_reversing_profile_rejected(self):
        for y in ([0.,0.,1.],[0.,1.,.9],[0.,float('nan'),1.]):
            with self.assertRaises(ValueError):AngularWarp(dict(clock_nodes=[0.,.5,1.],angle_nodes=y))

    def test_acceleration_matches_derivative_of_velocity(self):
        bank=TrajectoryBank(settings(),.7,.4)
        for clock in (.123,.303,.553,.843):
            p=bank.make('low_swing',clock,0);analytic=p.template_acceleration;epsilon=1e-6
            p.phase=clock+p.speed*epsilon;plus=p.coordinate_velocity
            p.phase=clock-p.speed*epsilon;minus=p.coordinate_velocity
            self.assertAlmostEqual(analytic,(plus-minus)/(2*epsilon),places=4)

class GearIntegrationTests(unittest.TestCase):
    def test_blank_images_keep_positive_template_clock_no_input(self):
        c,m,_=jump_rope.load(ROOT);vision,controller=jump_rope.phase_rope_components(ROOT,c,m,gear=True)
        for i in range(20):
            o=vision.detect(np.zeros((180,320,3),np.uint8),i*.02)
            self.assertGreater(o['phase_estimate']['clock_rate'],0)
            self.assertFalse(o['rope_valid']);json.dumps(o)
        self.assertFalse(controller(c).step(o,.4,False)['down'])

    def test_gear_cli_rejects_input_before_computer_creation(self):
        for flag in ('--live','--experimental-live','--test-space'):
            with patch('sys.argv',['jump_rope','--phase-rope','--phase-gear',flag]),patch.object(jump_rope,'ActionComputer') as computer:
                with self.assertRaises(SystemExit):jump_rope.main()
                computer.assert_not_called()

    def test_profiles_cannot_mix(self):
        with self.assertRaisesRegex(ValueError,'requires phase-rope'):jump_rope.run_jump_rope(ROOT,None,0,phase_gear=True)
        with self.assertRaisesRegex(ValueError,'one phase profile'):jump_rope.run_jump_rope(ROOT,None,0,phase_rope=True,phase_gear=True,phase_state=True)
