"""Continuous control regression: fresh leases, held W, feedback and release."""
import math
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.patrol import Position
from modular_agent.domains.hololive_dreams.camera_navigation import CameraWRouteFollower,CameraHeading,CruiseDecision
from modular_agent.realtime.camera_navigation import ContinuousRouteExecutor


class ContinuousRouteTests(unittest.TestCase):
    def test_fast_cruise_steering_keeps_w_held_and_uses_bounded_mouse_steps(self):
        e,c,g,clock,events=self.executor()
        e.execute(CruiseDecision(mouse_dx=360,counts_per_second=2400),observed_at=0)
        for tick in range(1,18):clock[0]=tick*.01;e._tick()
        self.assertEqual(sum(a.arguments.get('dx',0) for a in events),360)
        self.assertEqual(c.keys,{'w'})
        self.assertTrue(all(abs(a.arguments['dx'])<=24 for a in events if a.name=='move_relative'))
        self.assertEqual(sum(a.name=='key_down' for a in events),1)

    def executor(self,*,real_thread=False):
        clock=[0.];events=[]
        computer=SimpleNamespace(keys=set(),buttons=set(),stopped=False,live=True)
        def perform(action):
            events.append(action)
            if action.name=='key_down':computer.keys.add(action.arguments['key'])
            return SimpleNamespace(outcome=Outcome.SUCCESS)
        computer.perform=perform
        computer.release_all=lambda:computer.keys.clear()
        guard=SimpleNamespace(check_fresh=lambda:None)
        if real_thread:
            executor=ContinuousRouteExecutor(computer,guard)
        else:
            with patch('modular_agent.realtime.camera_navigation.threading.Thread') as thread:
                thread.return_value.is_alive.return_value=False
                executor=ContinuousRouteExecutor(computer,guard,clock=lambda:clock[0])
        self.addCleanup(executor.close)
        return executor,computer,guard,clock,events

    def follower(self):
        return CameraWRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='walk',points=[[180,100],[180,180]])]),
            np.full((240,240),255,np.uint8),degrees_per_count=.071,continuous=True)

    def step(self,f,t,x=50,y=100,yaw=0,valid=True,**kw):
        return f.step(Position(x,y,t,valid=valid),round(t*1000)+1,t,heading=CameraHeading(yaw,t,True),**kw)

    def test_renewals_hold_w_once_and_steer_while_moving(self):
        e,c,g,clock,events=self.executor()
        for t in (0,.15,.30,.45,.60):
            clock[0]=t
            d=e.prepare(CruiseDecision(mouse_dx=30),observed_at=t)
            self.assertTrue(e.execute(d,observed_at=t))
            clock[0]+=.02;e._tick()
            self.assertEqual(c.keys,{'w'})
        self.assertEqual(sum(a.name=='key_down' for a in events),1)
        self.assertTrue(any(a.name=='move_relative' for a in events))
        self.assertTrue(all(abs(a.arguments['dx'])<=4 for a in events if a.name=='move_relative'))
        e.pause();self.assertFalse(c.keys)

    def test_expiry_cannot_be_extended_by_late_recognition(self):
        e,c,g,clock,events=self.executor()
        clock[0]=.2;d=e.prepare(CruiseDecision(),observed_at=0)
        e.execute(d,observed_at=0)
        self.assertLessEqual(e.command['deadline'],.5)
        clock[0]=.51;e._tick()
        self.assertFalse(c.keys);self.assertEqual(e.expirations,1)
        self.assertIsNone(e.prepare(CruiseDecision(),observed_at=0))

    def test_independent_worker_releases_when_main_loop_stalls(self):
        e,c,g,clock,events=self.executor(real_thread=True)
        stamp=time.perf_counter()
        e.execute(CruiseDecision(duration=.06),observed_at=stamp)
        self.assertEqual(c.keys,{'w'})
        deadline=time.perf_counter()+.5
        while c.keys and time.perf_counter()<deadline:time.sleep(.005)
        self.assertFalse(c.keys);self.assertEqual(e.expirations,1)

    def test_worker_start_failure_and_close_release_all_input(self):
        e,c,g,clock,events=self.executor()
        e.execute(CruiseDecision(),observed_at=0)
        e.close();self.assertFalse(c.keys)
        c.keys.add('w')
        with patch('modular_agent.realtime.camera_navigation.threading.Thread') as thread:
            thread.return_value.start.side_effect=RuntimeError('thread failed')
            with self.assertRaises(RuntimeError):ContinuousRouteExecutor(c,g)
        self.assertFalse(c.keys)

    def test_cancel_popup_disabled_focus_or_stale_guard_releases(self):
        for reason in ('cancelled','popup','disabled','unfocused','stale_or_blocked_scene'):
            with self.subTest(reason=reason):
                e,c,g,clock,events=self.executor()
                e.execute(CruiseDecision(),observed_at=0)
                def reject():raise RuntimeError(reason)
                g.check_fresh=reject
                clock[0]=.02;e._tick()
                self.assertFalse(c.keys);self.assertEqual(e.error,reason)
                with self.assertRaises(RuntimeError):e.prepare(CruiseDecision(),observed_at=.02)

    def test_dropped_keydown_does_not_create_active_lease(self):
        e,c,g,clock,events=self.executor()
        c.perform=lambda action:SimpleNamespace(outcome='failure',message='dropped')
        with self.assertRaises(RuntimeError):e.execute(CruiseDecision(),observed_at=0)
        self.assertFalse(c.keys)
        self.assertIsNone(e.command)

    def test_rejects_asd_and_invalid_long_leases(self):
        e,c,g,clock,events=self.executor()
        for decision in (CruiseDecision(keys=('a',)),CruiseDecision(duration=1),CruiseDecision(mouse_dx=100)):
            with self.assertRaises(ValueError):e.execute(decision,observed_at=0)
        self.assertFalse(events)

    def test_cruises_without_settling_each_frame_and_corrects_heading(self):
        f=self.follower();self.step(f,0)
        first=self.step(f,.2);self.assertEqual(first.kind,'cruise');f.dispatched(first,.2)
        correction=self.step(f,.4,x=56,yaw=5)
        self.assertEqual(correction.kind,'cruise');self.assertLess(correction.mouse_dx,0)
        f.dispatched(correction,.4)
        self.assertEqual(self.step(f,.6,x=62,yaw=3).kind,'cruise')

    def test_brakes_for_goal_large_error_lost_position_and_blocked_corridor(self):
        cases=[dict(x=171),dict(yaw=35),dict(valid=False)]
        for kw in cases:
            f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
            self.assertEqual(self.step(f,.4,**kw).kind,'wait');self.assertFalse(f.cruising)
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
        f.mask[100,65]=0
        self.assertEqual(self.step(f,.4,x=55).kind,'stop')

    def test_remaining_distance_shortens_lease_instead_of_repeated_stops(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
        d=self.step(f,.4,x=164)
        self.assertEqual(d.kind,'cruise')
        self.assertLess(d.duration,.5)
        self.assertAlmostEqual(d.duration,(16-3-6)/28.5)

    def test_dropped_w_stops_from_visual_progress_not_lease_success(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
        self.assertEqual(self.step(f,5.3).reason,'stuck_no_visual_progress')

    def test_dropped_steering_stops_without_blind_renewals(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
        d=self.step(f,.4,x=56,yaw=5);f.dispatched(d,.4)
        self.assertEqual(self.step(f,1.5,x=85,yaw=5).reason,'camera_turn_not_observed')

    def test_continuous_route_simulation_reaches_corner_and_end(self):
        f=self.follower();xy=np.array([50.,100.]);yaw=0.;t=0.;consecutive=0;longest=0
        for frame in range(1,1200):
            d=f.step(Position(*xy,t),frame,t,heading=CameraHeading(yaw,t,True))
            if d.kind=='stop':break
            if d.kind=='cruise':
                consecutive+=1;longest=max(longest,consecutive)
                yaw=(yaw+np.clip(d.mouse_dx,-48,48)*.071)%360
                xy+=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])*28.5*.2
                f.dispatched(d,t)
            elif d.kind=='turn':
                consecutive=0;yaw=(yaw+d.mouse_dx*.071)%360;f.dispatched(d,t+d.duration)
            elif d.kind=='move':
                consecutive=0;xy+=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])*28.5*d.duration
                f.dispatched(d,t+d.duration)
            else:consecutive=0
            t+=.2
        self.assertGreater(longest,10)
        self.assertEqual(d.reason,'route_traversed_collection_unverified')


if __name__=='__main__':unittest.main()
