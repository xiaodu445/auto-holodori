import unittest
from types import SimpleNamespace
import numpy as np
from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.patrol import Position,MotionCalibration,Decision
from modular_agent.domains.hololive_dreams.route_execution import AutoRouteFollower,MotionProbe
from modular_agent.realtime.patrol import GuardedPulseExecutor
from modular_agent.realtime.route_scene import RouteSceneGate


class RouteExecutionTests(unittest.TestCase):
    def follower(self,jump=False):
        segment=dict(kind='jump' if jump else 'walk',points=[[50,50],[90,50]],verified=True)
        return AutoRouteFollower(dict(planning='annotation_astar',segments=[segment]),
            np.full((160,160),255,np.uint8),MotionCalibration(dict(w=(0,-100),a=(-100,0),s=(0,100),d=(100,0))))

    def step(self,f,x,t,frame=None,**kw):return f.step(Position(x,50,t),frame if frame is not None else int(t*100)+1,t,**kw)

    def test_walk_is_visual_not_input_completion(self):
        f=self.follower();self.step(f,50,0)
        d=self.step(f,50,.1);self.assertEqual(d.keys,('d',))
        f.dispatched(d,.22)
        self.assertEqual(f.index,1)
        self.assertEqual(self.step(f,50,.25).reason,'settling')
        self.assertEqual(self.step(f,90,.5).reason,'waypoint_observed')
        self.assertEqual(self.step(f,90,.6).kind,'stop')

    def test_dropped_movement_stops_after_no_progress(self):
        f=self.follower();self.step(f,50,0);d=self.step(f,50,.1);f.dispatched(d,.2)
        self.assertEqual(self.step(f,50,4.3).reason,'stuck_no_visual_progress')

    def test_popup_disabled_scene_and_cancel_stop(self):
        for kw in ({'free_scene':False},{'cancelled':True}):
            f=self.follower();self.assertEqual(self.step(f,50,0,**kw).kind,'stop')
            self.assertEqual(self.step(f,50,.1).kind,'stop')

    def test_stale_or_invalid_does_not_move(self):
        f=self.follower()
        self.assertEqual(f.step(Position(50,50,0),1,1).kind,'wait')
        self.assertEqual(f.step(Position(50,50,1,valid=False),2,1).kind,'wait')

    def test_jump_space_once_then_two_fresh_landing_frames(self):
        f=self.follower(True);d=self.step(f,50,0)
        self.assertEqual(d.keys,('d','space'));f.dispatched(d,.12)
        self.assertNotIn('space',self.step(f,65,.4).keys)
        self.assertEqual(self.step(f,90,.7).kind,'wait');self.assertEqual(f.index,0)
        self.assertEqual(self.step(f,90,.8).reason,'jump_landing_position_observed')
        self.assertEqual(f.index,1)

    def test_dropped_space_has_no_blind_retry(self):
        f=self.follower(True);d=self.step(f,50,0);f.dispatched(d,.12)
        self.assertNotIn('space',self.step(f,50,.5).keys)
        self.assertEqual(self.step(f,50,2.2).reason,'jump_landing_timeout_no_retry')

    def test_unverified_jump_rejected(self):
        with self.assertRaises(ValueError):
            AutoRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='jump',points=[[50,50],[90,50]])]),
                self.follower().mask,self.follower().motion)

    def test_jump_invalid_frame_resets_landing_confirmation(self):
        f=self.follower(True);d=self.step(f,50,0);f.dispatched(d,.12)
        self.step(f,90,.7)
        f.step(Position(90,50,.8,valid=False),81,.8)
        self.step(f,90,.9);self.assertEqual(f.index,0)
        self.step(f,90,1);self.assertEqual(f.index,1)

    def test_calibration_rejects_obstacles_and_dropped_input(self):
        mask=np.full((180,180),255,np.uint8);mask[90,100]=0
        with self.assertRaises(ValueError):MotionProbe(mask).step(Position(90,90,0),0)
        p=MotionProbe(np.full_like(mask,255));d=p.step(Position(90,90,0),0)
        p.dispatched(d,Position(90,90,0),.15)
        with self.assertRaises(ValueError):p.step(Position(90,90,.7),.7)

    def test_measured_four_probes(self):
        p=MotionProbe(np.full((220,220),255,np.uint8));x=y=110;t=0
        for dx,dy in ((0,-15),(-15,0),(0,15),(15,0)):
            d=p.step(Position(x,y,t),t)
            self.assertEqual(d.kind,'move');p.dispatched(d,Position(x,y,t),t+.15)
            x+=dx;y+=dy;t+=.7
        self.assertEqual(p.step(Position(x,y,t),t).reason,'calibration_complete')
        self.assertEqual(p.motion.vectors['d'],(100.,0.))

    def test_delayed_popup_vetoes_even_with_hud(self):
        gate=RouteSceneGate.__new__(RouteSceneGate)
        gate.enabled=lambda im:True
        gate.root=None;gate.hud=SimpleNamespace(read=lambda im:(True,1))
        gate.extract=lambda *args:dict(hud_count=5,reward=True)
        self.assertFalse(gate.read(None)[0])
        gate.extract=lambda *args:dict(world_support=2)
        self.assertTrue(gate.read(None)[0])
        gate.extract=lambda *args:dict(hud_count=2)
        self.assertFalse(gate.read(None)[0])

    def test_real_free_scene_and_gray_disabled_hud(self):
        import cv2
        from modular_agent.realtime.patrol import DATA,ROOT
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        image=read_image(DATA/'references/free-world.png')[38:,:1260]
        gate=RouteSceneGate(ROOT)
        self.assertTrue(gate.read(image)[0])
        gray=cv2.cvtColor(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        self.assertFalse(gate.read(gray)[0])

    def test_closed_loop_simulation_finishes_with_only_short_pulses(self):
        motion=self.follower().motion
        f=AutoRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='walk',points=[[50,50],[110,50],[110,110],[50,110],[50,50]])]),
            np.full((160,160),255,np.uint8),motion)
        xy=np.array([50.,50.]);t=0;count=0
        for frame in range(1,501):
            d=f.step(Position(*xy,t),frame,t)
            if d.kind=='stop':break
            if d.kind=='move':
                self.assertLessEqual(d.duration,.12)
                xy+=np.asarray(motion.vectors[d.keys[0]])*d.duration
                f.dispatched(d,t+d.duration);count+=1
            t+=.3
        self.assertEqual(d.reason,'route_traversed_collection_unverified')
        self.assertGreater(count,4);self.assertLess(np.linalg.norm(xy-[50,50]),3)


class JumpExecutorTests(unittest.TestCase):
    def test_two_route_sessions_cannot_own_input(self):
        import os,tempfile
        from pathlib import Path
        from modular_agent.realtime.patrol import route_input_lease
        if os.name!='nt':self.skipTest('Windows route input lease')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.lock'
            with route_input_lease(path):
                with self.assertRaises(RuntimeError):
                    with route_input_lease(path):pass
            with route_input_lease(path):pass

    def test_second_key_failure_and_midpulse_cancel_release(self):
        for fail_space in (True,False):
            c=SimpleNamespace(live=True,keys=set(),buttons=set(),stopped=False)
            events=[];clock=[0.]
            def perform(action):
                key=action.arguments['key'];c.keys.add(key);events.append(key)
                return SimpleNamespace(outcome=Outcome.FAILURE if fail_space and key=='space' else Outcome.SUCCESS,message='dropped')
            c.perform=perform;c.release_all=lambda:c.keys.clear()
            def check():
                if clock[0]>.02:raise RuntimeError('cancelled')
            def sleep(dt):clock[0]+=dt
            with self.assertRaises(RuntimeError):
                GuardedPulseExecutor(c,check,live=True,clock=lambda:clock[0],sleep=sleep).execute(
                    Decision('jump','test',('d','space'),.12),observed_at=0)
            self.assertEqual(events,['d','space']);self.assertFalse(c.keys)


if __name__=='__main__':unittest.main()
