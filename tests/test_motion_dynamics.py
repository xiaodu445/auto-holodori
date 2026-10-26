import math
from types import SimpleNamespace
import unittest
import numpy as np
from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.motion_dynamics import camera_headings,fit_camera,fit_forward,measure_cruise
from modular_agent.domains.hololive_dreams.patrol import Position
from modular_agent.realtime.motion_probe import require_open_disk,observed_hold,turn_step,validated_walk_mask,SmoothTurn,require_forward_space


class CameraTests(unittest.TestCase):
    def test_archived_partial_live_sweep_is_consistent_but_not_full_turn(self):
        import json
        from modular_agent.realtime.patrol import DATA
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        folder=DATA/'camera-regression-m012';source=json.loads((folder/'source.json').read_text())
        headings,_=camera_headings([read_image(folder/f'{n:06d}.png') for n in source['frame_ids']])
        report=fit_camera(source['counts'],headings)
        self.assertFalse(report['full_turn_observed'])
        self.assertLess(report['angle_rms_degrees'],2)
        self.assertEqual(report['direction'],'counterclockwise')
    def images(self):
        rng=np.random.default_rng(41)
        base=rng.integers(60,170,(164,164,3),np.uint8)
        yy,xx=np.mgrid[:164,:164];angle=np.rad2deg(np.arctan2(yy-82,xx-82));frames=[]
        for heading in range(0,391,10):
            image=base.copy();wedge=np.abs((angle-heading+180)%360-180)<48
            image[:,:,2]+=wedge.astype(np.uint8)*30;image[:,:,0]-=wedge.astype(np.uint8)*20
            # An actor marker pointing DOWN stays fixed while the camera turns.
            image[82:105,78:86]=255
            frames.append(image)
        return frames

    def test_cone_is_independent_of_actor_and_yellow_static_terrain(self):
        headings,quality=camera_headings(self.images())
        for i,h in enumerate(headings):self.assertLess(abs((h-i*10+180)%360-180),1)
        report=fit_camera(np.arange(37)*20,headings[:37])
        self.assertAlmostEqual(report['counts_per_360'],720,delta=2)
        self.assertTrue(report['full_turn_observed']);self.assertFalse(report['hardware_dpi_measured'])

    def test_partial_sweep_uses_unobserved_pixels_as_unknown_not_no_cone(self):
        headings,quality=camera_headings(self.images()[:23])
        for index,heading in enumerate(headings):
            self.assertIsNotNone(heading)
            self.assertLess(abs((heading-index*10+180)%360-180),2)

    def test_350_degrees_is_not_a_full_turn_and_negative_counts_can_complete(self):
        self.assertFalse(fit_camera(np.arange(36)*20,[(i*10)%360 for i in range(36)])['full_turn_observed'])
        result=fit_camera(-np.arange(38)*20,[(-i*10)%360 for i in range(38)])
        self.assertTrue(result['full_turn_observed']);self.assertEqual(result['direction'],'counterclockwise')

    def test_no_mouse_response_or_static_yellow_ground_has_no_heading(self):
        image=self.images()[0]
        headings,_=camera_headings([image]*12)
        self.assertTrue(all(h is None for h in headings))
        with self.assertRaises(ValueError):fit_camera(np.arange(12)*20,headings)

    def test_partial_turn_is_extrapolation_and_missing_gap_not_unwrapped(self):
        report=fit_camera(np.arange(15)*20,[i*10 for i in range(15)])
        self.assertFalse(report['full_turn_observed'])
        with self.assertRaises(ValueError):fit_camera(np.arange(15)*20,[0,None,20,None,40,None,60,None,80,None,100,None,120,None,140])

    def test_reverse_sensitivity_and_large_alias_steps(self):
        report=fit_camera(np.arange(40)*20,[(-i*10)%360 for i in range(40)])
        self.assertLess(report['degrees_per_count'],0)
        with self.assertRaises(ValueError):fit_camera(np.arange(10),[(i*100)%360 for i in range(10)])


class ForwardTests(unittest.TestCase):
    def test_explicit_open_ground_needs_no_annotation_but_still_needs_position(self):
        require_forward_space(None,Position(100,100,0),.3,open_ground=True)
        with self.assertRaises(ValueError):require_forward_space(None,Position(100,100,0),.3)
        with self.assertRaises(ValueError):require_forward_space(None,Position(100,100,0,valid=False),.15,open_ground=True)
        require_forward_space(None,Position(100,100,0),1.2,open_ground=True)
        with self.assertRaises(ValueError):require_forward_space(None,Position(100,100,0),2.01,open_ground=True)

    def trial(self,duration,interval=.01):
        rise=.08;decay=.12;speed=60;samples=[]
        for t in np.arange(0,duration+.9,interval):
            on=min(t,duration)
            x=speed*(on-rise*(1-math.exp(-on/rise))+(1-math.exp(-duration/rise))*decay*(1-math.exp(-max(t-duration,0)/decay)))
            samples.append(dict(t=float(t),x=x,y=0))
        return dict(held_seconds=duration,samples=samples)

    def test_known_acceleration_and_coast_model_recovered(self):
        report=fit_forward([self.trial(.15),self.trial(.3)])
        self.assertAlmostEqual(report['model_terminal_speed_pixels_per_second'],60,delta=2)
        self.assertIsNone(report['steady_speed_pixels_per_second'])
        self.assertAlmostEqual(report['acceleration_time_constant_seconds'],.08,delta=.015)
        self.assertAlmostEqual(report['damping_time_constant_seconds'],.12,delta=.015)
        self.assertTrue(report['dynamics_resolved'])

    def test_long_hold_measures_actual_cruise_speed_independently(self):
        trials=[self.trial(.3),self.trial(.6),self.trial(1.2)]
        report=measure_cruise(trials)
        self.assertTrue(report['plateau_observed'])
        self.assertAlmostEqual(report['steady_speed_pixels_per_second'],60,delta=2)
        self.assertTrue(fit_forward(trials)['plateau_observed'])

    def test_still_accelerating_or_stationary_has_no_cruise_plateau(self):
        trial=dict(held_seconds=1.2,samples=[dict(t=float(t),x=20*float(t)**2,y=0) for t in np.arange(0,1.2,.02)])
        self.assertFalse(measure_cruise([trial])['plateau_observed'])
        for sample in trial['samples']:sample['x']=0
        self.assertFalse(measure_cruise([trial])['plateau_observed'])

    def test_dropped_w_or_collided_movement_not_fitted(self):
        trials=[self.trial(.15),self.trial(.3)]
        for trial in trials:
            for row in trial['samples']:row['x']=0
        with self.assertRaises(ValueError):fit_forward(trials)

    def test_low_sample_rate_not_claimed_resolved(self):
        report=fit_forward([self.trial(.3,.1),self.trial(.5,.1)])
        self.assertFalse(report['dynamics_resolved'])

    def test_unknown_ground_or_no_localization_prevents_w(self):
        mask=np.full((250,250),255,np.uint8)
        require_open_disk(mask,Position(125,125,0),.3)
        mask[125,145]=0
        with self.assertRaises(ValueError):require_open_disk(mask,Position(125,125,0),.3)
        with self.assertRaises(ValueError):require_open_disk(mask,Position(125,125,0,valid=False),.15)

    def test_same_size_wrong_map_mask_is_rejected_before_input(self):
        import tempfile,json
        from pathlib import Path
        from modular_agent.domains.hololive_dreams.patrol_vision import write_image
        from modular_agent.domains.hololive_dreams.navigation_annotations import digest
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);image=np.full((100,100,3),140,np.uint8)
            write_image(folder/'map.png',image);write_image(folder/'planning-mask.png',np.full((100,100),255,np.uint8))
            (folder/'patrol-config.json').write_text(json.dumps(dict(reference='map.png')))
            (folder/'planned-route.json').write_text(json.dumps(dict(map_sha256=digest(folder/'map.png'),planning_mask='planning-mask.png')))
            self.assertEqual(validated_walk_mask(folder/'patrol-config.json',folder/'planning-mask.png').shape,(100,100))
            image[:]=155;write_image(folder/'map.png',image)
            with self.assertRaises(ValueError):validated_walk_mask(folder/'patrol-config.json',folder/'planning-mask.png')


class HoldTests(unittest.TestCase):
    def test_continuous_mouse_runs_while_main_thread_is_busy(self):
        import time
        events=[];computer=SimpleNamespace(keys=set(),buttons=set(),perform=lambda action:SimpleNamespace(outcome=Outcome.SUCCESS))
        turner=SmoothTurn(computer,200,16,lambda:None,events.append)
        turner.start()
        try:time.sleep(.2)
        finally:turner.stop()
        self.assertIsNone(turner.error);self.assertEqual(sum(events),16)
        self.assertTrue(all(0<d<=4 for d in events));self.assertGreater(len(events),3)

    def test_continuous_mouse_stops_on_focus_loss(self):
        import time
        events=[];computer=SimpleNamespace(keys=set(),buttons=set(),perform=lambda action:SimpleNamespace(outcome=Outcome.SUCCESS))
        def check():
            if sum(events)>=4:raise RuntimeError('focus_lost')
        turner=SmoothTurn(computer,200,100,check,events.append);turner.start()
        try:time.sleep(.08)
        finally:turner.stop()
        self.assertIsInstance(turner.error,RuntimeError);self.assertLessEqual(sum(events),7)

    def computer(self):
        computer=SimpleNamespace(keys=set(),buttons=set(),stopped=False)
        def perform(action):
            computer.keys.add('w');return SimpleNamespace(outcome=Outcome.SUCCESS)
        computer.perform=perform;computer.release_all=lambda:computer.keys.clear()
        return computer

    def test_cancel_or_delayed_popup_during_capture_releases_w(self):
        for why in ('cancelled','delayed_popup','disabled_control'):
            computer=self.computer()
            def observe():raise RuntimeError(why)
            with self.assertRaisesRegex(RuntimeError,why):observed_hold(computer,.05,lambda:None,observe)
            self.assertFalse(computer.keys)

    def test_failed_key_delivery_is_not_retried(self):
        computer=self.computer();calls=[]
        def failed(action):calls.append(action);return SimpleNamespace(outcome=Outcome.FAILURE,message='dropped')
        computer.perform=failed
        with self.assertRaises(RuntimeError):observed_hold(computer,.05,lambda:None,lambda:None)
        self.assertEqual(len(calls),1);self.assertFalse(computer.keys)

    def test_slow_vision_does_not_extend_the_w_hold(self):
        import time
        computer=self.computer();frames=[]
        def observe():
            time.sleep(.09)
            frames.append(bool(computer.keys))
            return dict(stamp=time.perf_counter(),x=0,y=0)
        result=observed_hold(computer,.05,lambda:None,observe,coast=.2)
        self.assertFalse(any(frames))
        self.assertLess(result['held_seconds'],.08)

    def test_turn_focus_loss_stops_remaining_mouse_steps(self):
        computer=self.computer();sent=[]
        def check():
            if sent:raise RuntimeError('focus_lost')
        with self.assertRaisesRegex(RuntimeError,'focus_lost'):turn_step(computer,24,check,sent.append)
        self.assertEqual(sent,[4])

    def test_watchdog_start_failure_still_releases_w(self):
        from unittest.mock import patch
        computer=self.computer()
        with patch('threading.Thread.start',side_effect=RuntimeError('thread unavailable')):
            with self.assertRaises(RuntimeError):observed_hold(computer,.05,lambda:None,lambda:None)
        self.assertFalse(computer.keys)


if __name__=='__main__':unittest.main()
