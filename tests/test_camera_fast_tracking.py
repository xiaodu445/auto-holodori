import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.patrol import Position
from modular_agent.domains.hololive_dreams.camera_navigation import (
    CameraWRouteFollower,CameraHeading,CameraTurn,VisualCameraHeading,paired_cone,angle_error)
from modular_agent.realtime.camera_navigation import GuardedCameraExecutor


class FastCameraTests(unittest.TestCase):
    def follower(self):
        return CameraWRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='walk',points=[[180,100]])]),
            np.full((240,240),255,np.uint8),degrees_per_count=.071,continuous=True,fast_turns=True)

    def step(self,f,t,yaw=90,source='reference_cone'):
        return f.step(Position(50,100,t),round(t*1000)+1,t,heading=CameraHeading(yaw,t,True,source,1))

    def test_calibrated_large_turn_instead_of_three_degree_steps(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2)
        self.assertEqual(d.kind,'turn');self.assertEqual(d.counts_per_second,7200)
        self.assertGreater(abs(d.mouse_dx),1000)
        self.assertLess(d.duration,.2)
        f.dispatched(d,.4)
        correction=self.step(f,.7,yaw=90+d.mouse_dx*.071)
        self.assertEqual(correction.kind,'turn')
        self.assertLess(abs(correction.mouse_dx),abs(d.mouse_dx))

    def test_source_change_is_not_a_mouse_response_measurement(self):
        f=self.follower();self.step(f,0,yaw=171);d=self.step(f,.2,yaw=171);f.dispatched(d,.4)
        d=self.step(f,.7,yaw=251.5,source='stationary_temporal_cone')
        self.assertEqual(d.kind,'wait');self.assertEqual(d.reason,'camera_heading_source_changed_reobserve')
        self.assertIsNone(f.pending_turn)

    def test_no_response_same_sensor_still_stops(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.4)
        self.assertEqual(self.step(f,1.5).reason,'camera_turn_not_observed')

    def test_fast_mouse_batch_and_cancel_are_bounded(self):
        for failure in (None,'cancelled','delayed_popup','disabled'):
            with self.subTest(failure=failure):
                clock=[0.];events=[]
                c=SimpleNamespace(keys=set(),buttons=set(),stopped=False,live=True,release_all=lambda:None)
                def perform(action):events.append(action);return SimpleNamespace(outcome=Outcome.SUCCESS)
                c.perform=perform
                def check():
                    if failure and clock[0]>.025:raise RuntimeError(failure)
                e=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
                d=e.prepare(CameraTurn(mouse_dx=1200,counts_per_second=7200),observed_at=0)
                if failure:
                    with self.assertRaises(RuntimeError):e.execute(d,observed_at=0)
                    self.assertLess(sum(a.arguments['dx'] for a in events),1200)
                else:
                    self.assertTrue(e.execute(d,observed_at=0))
                    self.assertEqual(e.last_decision.mouse_dx,1200)
                    self.assertLess(clock[0],.2)
                self.assertTrue(all(abs(a.arguments['dx'])<=128 for a in events))


class PairedConeTests(unittest.TestCase):
    def test_cruise_mouse_updates_old_turn_prediction_without_fabricating_visual(self):
        reader=VisualCameraHeading(np.zeros((240,240,3),np.uint8))
        reader.last_good=(np.zeros((164,164,3),np.uint8),175.,0)
        reader.expect_rotation(100,.071,.1)
        reader.apply_mouse_delta(-200,.071)
        self.assertAlmostEqual(reader.expected[0],167.9)
        self.assertEqual(reader.last_good[1],175)
        self.assertEqual(reader.good,0)

    def scene(self,heading):
        base=np.random.default_rng(19).integers(60,170,(164,164,3),np.uint8)
        yy,xx=np.mgrid[:164,:164];angles=np.rad2deg(np.arctan2(yy-82,xx-82))
        wedge=np.abs((angles-heading+180)%360-180)<=46
        base[:,:,2]+=wedge.astype(np.uint8)*30;base[:,:,0]-=wedge.astype(np.uint8)*20
        base[65:100,78:88]=255
        return base

    def test_both_signed_edges_track_small_fast_and_wraparound_turns(self):
        for before,after in ((170,175),(170,165),(350,5),(5,350),(45,135),(135,45)):
            with self.subTest(before=before,after=after):
                degree,confidence=paired_cone(self.scene(before),self.scene(after),before)
                self.assertIsNotNone(degree)
                self.assertLess(abs(angle_error(degree,after)),2)
                self.assertGreater(confidence,.7)

    def test_static_frame_and_single_boundary_do_not_invent_rotation(self):
        old=self.scene(170);new=self.scene(180)
        self.assertIsNone(paired_cone(old,old,170)[0])
        warmth=new[:,:,2].astype(float)-new[:,:,0]-old[:,:,2]+old[:,:,0]
        new[warmth<0]=old[warmth<0]
        self.assertIsNone(paired_cone(old,new,170)[0])

    def test_real_failure_pair_stays_near_reference_not_eighty_degree_flip(self):
        from modular_agent.realtime.patrol import DATA
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        folder=DATA/'camera-regression-m017'
        degree,confidence=paired_cone(read_image(folder/'first.png'),read_image(folder/'last.png'),161)
        self.assertIsNotNone(degree)
        self.assertLess(abs(angle_error(degree,171)),5)
        self.assertGreater(abs(angle_error(degree,251.5)),60)

    def test_mouse_prediction_rejects_visual_jump_but_never_makes_heading(self):
        image=np.full((164,164,3),150,np.uint8)
        reader=VisualCameraHeading(np.full((240,240,3),150,np.uint8))
        module='modular_agent.domains.hololive_dreams.camera_navigation.'
        with patch(module+'reference_cone',return_value=(171.,.9)),patch(module+'paired_cone',return_value=(None,0)):
            reader.read(image,Position(100,100,0),0);self.assertTrue(reader.read(image,Position(100,100,.2),.2).valid)
        reader.expect_rotation(34,.071,.3)
        with patch(module+'reference_cone',return_value=(251.5,.95)),patch(module+'paired_cone',return_value=(None,0)):
            result=reader.read(image,Position(100,100,.4),.4)
            self.assertFalse(result.valid);self.assertEqual(result.source,'cone_prediction_disagreement')
        with patch(module+'reference_cone',return_value=(None,0)),patch(module+'paired_cone',return_value=(None,0)):
            self.assertFalse(reader.read(image,Position(100,100,.6),.6).valid)


if __name__=='__main__':unittest.main()
