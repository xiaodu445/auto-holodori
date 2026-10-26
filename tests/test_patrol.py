import json
from pathlib import Path
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.interaction import policy_for
from modular_agent.domains.hololive_dreams.patrol import (
    Decision,MotionCalibration,Observation,PatrolController,PatrolSettings,Position,astar,
)
from modular_agent.domains.hololive_dreams.patrol_vision import (
    MinimapLocalizer,PickupPromptDetector,MinimapSpec,read_image,
)
from modular_agent.realtime.patrol import GuardedPulseExecutor

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'domains/hololive_dreams/data/patrol'


def motion():
    return MotionCalibration({'w':(0,-80),'s':(0,80),'a':(-80,0),'d':(80,0)})


def obs(i,t,x=0,y=0,**kw):
    return Observation(i,t,Position(x,y,t),True,**kw)


class ControllerTests(unittest.TestCase):
    def test_scenario_semantics(self):
        self.assertEqual(policy_for('patrol_movement').mode,'realtime')
        self.assertEqual(policy_for('patrol_pickup').mode,'claim')

    def test_move_reduces_error_and_is_bounded(self):
        c = PatrolController([(100,0)],motion())
        d = c.step(obs(0,0),0)
        self.assertEqual((d.kind,d.keys),('move',('d',)))
        self.assertLessEqual(d.duration,.15)

    def test_await_new_frame_after_pulse(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0),0)
        self.assertEqual(c.step(obs(1,.1),.1).reason,'await_post_input_frame')
        self.assertEqual(c.step(obs(2,.3,x=10),.3).kind,'move')

    def test_no_motion_without_calibration(self):
        c = PatrolController([(100,0)])
        self.assertEqual(c.step(obs(0,0),0).reason,'motion_calibration_required')

    def test_unknown_scene_and_popup_zero_input(self):
        for o in (Observation(0,0,Position(0,0,0),False),obs(0,0,blocked=True)):
            c = PatrolController([(100,0)],motion())
            self.assertEqual(c.step(o,0).kind,'wait')

    def test_localization_loss_zero_input(self):
        c = PatrolController([(100,0)],motion())
        self.assertEqual(c.step(Observation(0,0,None,True),0).reason,'localization_unavailable')

    def test_stale_and_future_frame_zero_input(self):
        for now,t in ((1,0),(0,1)):
            c = PatrolController([(100,0)],motion())
            self.assertEqual(c.step(obs(0,t),now).reason,'stale_frame')

    def test_duplicate_frame_zero_input(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0),0)
        self.assertEqual(c.step(obs(0,0),.3).reason,'stale_frame')

    def test_cancel_is_terminal(self):
        c = PatrolController([(100,0)],motion())
        self.assertEqual(c.step(obs(0,0),0,cancelled=True).reason,'cancelled')
        self.assertEqual(c.step(obs(1,1),1).kind,'stop')

    def test_stuck_stops_without_blind_recovery(self):
        c = PatrolController([(100,0)],motion(),PatrolSettings(stuck_seconds=1))
        c.step(obs(0,0),0)
        self.assertEqual(c.step(obs(1,1.1),1.1).reason,'stuck_replan_required')

    def test_arrival_and_lap_not_collection_verification(self):
        c = PatrolController([(0,0),(20,0)],motion())
        self.assertEqual(c.step(obs(0,0),0).reason,'waypoint_visited')
        self.assertEqual(c.step(obs(1,1,x=20),1).reason,'route_traversed_collection_unverified')
        self.assertEqual(c.summary()['waypoints_visited'],2)
        self.assertFalse(c.summary()['collection_verified'])

    def test_lap_budget(self):
        c = PatrolController([(0,0)],motion(),PatrolSettings(max_laps=2))
        self.assertEqual(c.step(obs(0,0),0).kind,'wait')
        self.assertEqual(c.step(obs(1,1),1).kind,'stop')
        self.assertEqual(c.laps,2)

    def test_closed_loop_simulated_route(self):
        c = PatrolController([(40,0),(40,40),(0,40),(0,0)],motion())
        x,y = 0.,0.
        for i in range(300):
            t = i*.3
            d = c.step(obs(i,t,x,y),t)
            if d.kind == 'move':
                vx,vy = c.motion.vectors[d.keys[0]]
                x += vx*d.duration;y += vy*d.duration
            if d.kind == 'stop':
                break
        self.assertEqual(c.halt_reason,'route_traversed_collection_unverified')
        self.assertEqual(c.visits,4)
        self.assertFalse(c.summary()['collection_verified'])

    def test_run_and_waypoint_budgets(self):
        for settings,reason in ((PatrolSettings(max_run_seconds=1),'run_budget'),
                                (PatrolSettings(waypoint_timeout=1),'waypoint_timeout')):
            c = PatrolController([(100,0)],motion(),settings)
            c.step(obs(0,0),0)
            self.assertEqual(c.step(obs(1,1.1),1.1).reason,reason)

    def test_disabled_prompt_never_sends(self):
        c = PatrolController([(100,0)],motion())
        for i in range(5):
            self.assertEqual(c.step(obs(i,i*.3,pickup_visible=True),i*.3).kind,'wait')
        self.assertEqual(c.pickup_sent,0)

    def test_delayed_enable(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0,pickup_visible=True),0)
        self.assertEqual(c.step(obs(1,.3,pickup_visible=True,pickup_enabled=True),.3).kind,'pickup')

    def test_dropped_input_limited_retry(self):
        c = PatrolController([(100,0)],motion())
        kinds = [c.step(obs(i,t,pickup_visible=True,pickup_enabled=True),t).kind
                 for i,t in enumerate((0,.3,1,1.9,3.5,5.1,7.9,8.1))]
        self.assertEqual(kinds.count('pickup'),3)
        self.assertEqual(c.halt_reason,'pickup_unconfirmed')
        self.assertEqual(c.pickup_results,0)

    def test_delayed_popup_suppresses_old_retry(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0,pickup_visible=True,pickup_enabled=True),0)
        c.step(obs(1,.3,pickup_visible=True,pickup_enabled=True),.3)
        c.step(obs(2,1,blocked=True),1)
        self.assertNotEqual(c.step(obs(3,2,pickup_visible=True,pickup_enabled=True),2).kind,'pickup')
        self.assertEqual(c.pickup_sent,1)

    def test_disappearance_not_reward(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0,pickup_visible=True,pickup_enabled=True),0)
        c.step(obs(1,.3,pickup_visible=True,pickup_enabled=True),.3)
        self.assertEqual(c.step(obs(2,1),1).kind,'wait')
        self.assertEqual(c.step(obs(3,1.3),1.3).kind,'move')
        self.assertEqual(c.pickup_results,0)

    def test_result_counted_once_per_episode(self):
        c = PatrolController([(100,0)],motion())
        c.step(obs(0,0,pickup_visible=True,pickup_enabled=True),0)
        c.step(obs(1,.3,pickup_visible=True,pickup_enabled=True),.3)
        c.step(obs(2,1,pickup_result=True,blocked=True),1)
        c.step(obs(3,1.3,pickup_result=True,blocked=True),1.3)
        self.assertEqual(c.pickup_results,1)

    def test_invalid_settings(self):
        for kw in ({'max_pulse':1},{'max_laps':1.5},{'max_frame_age':float('nan')}):
            with self.assertRaises(ValueError):
                PatrolSettings(**kw)


class PlanningTests(unittest.TestCase):
    def test_calibration_coverage_and_pulses(self):
        m = motion();m.validate()
        for x,y,key in ((100,0,'d'),(-100,0,'a'),(0,-100,'w'),(0,100,'s')):
            self.assertEqual(m.pulse((x,y),PatrolSettings())[0],(key,))

    def test_same_heading_rejected(self):
        with self.assertRaises(ValueError):
            MotionCalibration({k:(1,20) for k in 'wasd'}).validate()

    def test_calibration_measured(self):
        m = MotionCalibration()
        m.add_sample('w',Position(10,10,0),Position(10,0,1),.5)
        self.assertEqual(m.vectors['w'],(0,-20))
        with self.assertRaises(ValueError):
            m.add_sample('a',Position(0,0,0),Position(0,0,1),.5)

    def test_astar_detours_and_respects_wall(self):
        mask = np.full((80,80),255,np.uint8);mask[:60,36:44] = 0
        path = astar(mask,(12,12),(68,12),cell=4,clearance=0)
        self.assertGreater(max(y for x,y in path),59)
        self.assertTrue(all(mask[int(y),int(x)] for x,y in path))

    def test_no_path_and_blocked_end(self):
        mask = np.full((80,80),255,np.uint8);mask[:,36:44] = 0
        with self.assertRaisesRegex(ValueError,'no walkable'):
            astar(mask,(12,12),(68,12),cell=4,clearance=0)
        with self.assertRaisesRegex(ValueError,'blocked'):
            astar(mask,(40,12),(68,12),cell=4,clearance=0)

    def test_clearance_closes_narrow_gap(self):
        mask = np.zeros((60,60),np.uint8);mask[28:32,:] = 255
        with self.assertRaises(ValueError):
            astar(mask,(10,30),(50,30),cell=2,clearance=3)


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        rng = np.random.default_rng(74)
        small = rng.integers(20,235,(30,40,3),dtype=np.uint8)
        cls.reference = cv2.resize(small,(400,300),interpolation=cv2.INTER_NEAREST)
        cls.patch = cls.reference[80:160,120:200].copy()
        cls.mask = np.full((80,80),255,np.uint8)

    def localizer(self,reference=None,**kw):
        return MinimapLocalizer(self.reference if reference is None else reference,
                                scales=(1,),analysis_scale=1,**kw)

    def test_known_location_two_frames(self):
        loc = self.localizer()
        self.assertFalse(loc.match_patch(self.patch,self.mask,0).valid)
        p = loc.match_patch(self.patch,self.mask,.1)
        self.assertTrue(p.valid)
        self.assertAlmostEqual(p.x,160,delta=1)
        self.assertAlmostEqual(p.y,120,delta=1)

    def test_mask_ignores_player_overlay(self):
        patch = self.patch.copy();patch[28:52,28:52] = (0,0,255)
        mask = self.mask.copy();mask[24:56,24:56] = 0
        loc = self.localizer(stable_frames=1)
        p = loc.match_patch(patch,mask,0)
        self.assertTrue(p.valid)
        self.assertAlmostEqual(p.x,160,delta=1)

    def test_duplicate_map_geometry_is_ambiguous(self):
        ref = self.reference.copy();ref[180:260,280:360] = self.patch
        p = self.localizer(ref,stable_frames=1).match_patch(self.patch,self.mask,0)
        self.assertFalse(p.valid)
        self.assertEqual(p.reason,'ambiguous_location')

    def test_blank_and_maskless_rejected(self):
        loc = self.localizer()
        self.assertFalse(loc.match_patch(np.full_like(self.patch,200),self.mask,0).valid)
        self.assertFalse(loc.match_patch(self.patch,np.zeros_like(self.mask),1).valid)

    def test_timestamp_and_implausible_jump(self):
        loc = self.localizer(stable_frames=1,max_speed=10)
        self.assertTrue(loc.match_patch(self.patch,self.mask,0).valid)
        self.assertEqual(loc.match_patch(self.patch,self.mask,0).reason,'nonfresh_timestamp')
        other = self.reference[180:260,280:360]
        # The short-interval tracking ROI must reject a far-away match.
        self.assertFalse(loc.match_patch(other,self.mask,.1).valid)
        # After a longer gap global search resumes, with a separate jump guard.
        self.assertEqual(loc.match_patch(other,self.mask,3).reason,'implausible_position_jump')

    def test_scaled_patch(self):
        patch = cv2.resize(self.patch,(40,40))
        loc = MinimapLocalizer(self.reference,scales=(1.5,2,2.5),analysis_scale=1,stable_frames=1,min_margin=.01)
        p = loc.match_patch(patch,np.full((40,40),255,np.uint8),0)
        self.assertTrue(p.valid,p)
        self.assertAlmostEqual(p.x,160,delta=3)
        self.assertEqual(p.scale,2)

    def test_minimap_roi_bounds(self):
        with self.assertRaises(ValueError):
            MinimapSpec(center_uv=(0,0)).crop(np.zeros((709,1260,3),np.uint8))

    def test_user_pickup_positive_free_negative_gray_disabled(self):
        det = PickupPromptDetector(read_image(DATA/'pickup-key.png'),read_image(DATA/'pickup-text.png'))
        pickup = read_image(DATA/'references/pickup.png')[38:,:1260]
        free = read_image(DATA/'references/free-world.png')[38:,:1260]
        self.assertTrue(det.read(pickup)['enabled'])
        self.assertFalse(det.read(free)['visible'])
        gray = cv2.cvtColor(cv2.cvtColor(pickup,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        self.assertFalse(det.read(gray)['enabled'])


class ExecutorTests(unittest.TestCase):
    def computer(self):
        c = SimpleNamespace(live=True,stopped=False,keys=set(),buttons=set(),events=[])
        def perform(action):
            c.events.append(action.name)
            c.keys.add(action.arguments['key'])
            return SimpleNamespace(outcome=Outcome.SUCCESS)
        def release():
            c.events.append('release_all');c.keys.clear()
        c.perform = perform;c.release_all = release
        return c

    def test_dry_run_never_injects(self):
        c = self.computer()
        GuardedPulseExecutor(c,lambda:None,clock=lambda:0).execute(Decision('move','test',('w',),.1),observed_at=0)
        self.assertEqual(c.events,[])

    def test_focus_guard_fails_before_input(self):
        c = self.computer()
        def check():
            raise RuntimeError('focus lost')
        with self.assertRaises(RuntimeError):
            GuardedPulseExecutor(c,check,live=True,clock=lambda:0).execute(Decision('move','test',('w',),.1),observed_at=0)
        self.assertEqual(c.events,[])

    def test_midpulse_failure_releases(self):
        c = self.computer();calls = []
        def check():
            calls.append(1)
            if len(calls)>1:
                raise RuntimeError('cancelled')
        with self.assertRaises(RuntimeError):
            GuardedPulseExecutor(c,check,live=True,clock=lambda:0).execute(Decision('move','test',('w',),.1),observed_at=0)
        self.assertEqual(c.events,['key_down','release_all'])
        self.assertFalse(c.keys)

    def test_stale_observation_zero_input(self):
        c = self.computer()
        with self.assertRaises(RuntimeError):
            GuardedPulseExecutor(c,lambda:None,live=True,clock=lambda:2).execute(Decision('pickup','test',('e',),.06),observed_at=0)
        self.assertEqual(c.events,[])

    def test_invalid_key_and_unbounded_pulse_rejected(self):
        for d in (Decision('move','test',('e',),.1),Decision('pickup','test',('e',),2)):
            with self.assertRaises(ValueError):
                GuardedPulseExecutor(self.computer(),lambda:None).execute(d,observed_at=0)


if __name__ == '__main__':
    unittest.main()
