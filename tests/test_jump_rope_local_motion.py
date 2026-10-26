import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.jump_rope import load,local_motion_components
ROOT=Path(__file__).resolve().parents[1]
class LocalMotionTests(unittest.TestCase):
 def setUp(self):
  self.c,m,_=load(ROOT);self.c.update(roi=[.475,.43,.655,.66],local_jump_band=[.44,.64],avatar_template=[.544,.448,.584,.518],avatar_search=[.525,.43,.605,.64]);self.v=m.LocalMotionVision(self.c,cv2.imread(str(ROOT/'domains/hololive_dreams/data/jump_rope_samples/reference.png'))[21:]);self.cls=m.LocalMotionController
 def image(self,y=None,color=(255,255,255)):
  a=np.zeros((230,180,3),np.uint8)
  cv2.line(a,(0,190),(179,190),(80,80,80),2)
  if y is not None:cv2.line(a,(0,y),(179,y),color,3)
  return a
 def test_static_shadow_is_not_rope(self):
  for i in range(10):self.assertFalse(self.v.detect(self.image(),i*.02)['rope_valid'])
 def test_yellow_moving_line_and_current_position(self):
  self.v.detect(self.image(70,(0,255,255)),0)
  o=self.v.detect(self.image(80,(0,255,255)),.02)
  self.assertTrue(o['rope_valid']);self.assertAlmostEqual(o['rope_y'],.51,delta=.008)
 def test_pulse_duplicate_guard_and_rearm(self):
  self.c['experimental_input']=True;p=self.cls(self.c)
  o=dict(avatar_valid=True,avatar_y=self.c['avatar_template'][1],rope_valid=True)
  ds=[p.step(o,i*.02,i>=3) for i in range(8)]
  self.assertEqual(p.jumps,1);self.assertTrue(ds[2]['down']);self.assertFalse(ds[4]['down'])
  for i in range(8,21):p.step(dict(o,rope_valid=False),i*.02)
  p.step(o,.42);d=p.step(o,.44)
  self.assertTrue(d['down']);self.assertEqual(p.jumps,2)
 def test_judgment_stale_and_missing_avatar_never_press(self):
  p=self.cls(self.c);o=dict(avatar_valid=True,avatar_y=self.c['avatar_template'][1],rope_valid=True)
  for i in range(6):self.assertFalse(p.step(o,i*.02)['down'])
  self.c['experimental_input']=True
  self.assertFalse(p.step(o,.12,True,frame_age=.1)['down'])
  self.assertFalse(p.step(dict(o,avatar_valid=False),.14)['down'])

class TrajectoryMotionTests(unittest.TestCase):
 def test_repeated_reference_does_not_track_static_rope(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m)
  ref=cv2.imread(str(ROOT/'domains/hololive_dreams/data/jump_rope_samples/reference.png'))[21:];h,w=ref.shape[:2];l,t,r,b=c['roi'];im=ref[round(t*h):round(b*h),round(l*w):round(r*w)]
  for i in range(8):self.assertFalse(v.detect(im,i*.02)['rope_valid'])
 def test_disappearance_does_not_rearm_consumed_pass(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m);p=cls(c);p.demo_pass_consumed=True
  for i in range(30):p.step(dict(valid=False,avatar_valid=True,avatar_y=c['avatar_template'][1],rope_valid=False),i*.02)
  self.assertTrue(p.demo_pass_consumed)

 def test_colored_moving_curve_detected_but_static_unlocks(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m)
  def frame(y,color):
   im=np.zeros((500,300,3),np.uint8);l,t,r,b=c['roi']
   for x1,x2 in c['rope_probes']:
    x1=round((x1-l)/(r-l)*300);x2=round((x2-l)/(r-l)*300);py=round((y-t)/(b-t)*500)
    cv2.line(im,(x1-2,py),(x2+2,py),color,2)
   return im
  for i in range(5):
   o=v.detect(frame(.3+i*.012,(0,220,240)),i*.02)
  self.assertTrue(o['rope_valid'],o)
  im=frame(.348,(0,220,240))
  for i in range(5,20):o=v.detect(im,i*.02)
  self.assertFalse(o['rope_valid'])
 def test_noisy_pair_cannot_enable_visible_trigger(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m);p=cls(c)
  p.samples.extend([(0,.27),(.02,.29)])
  p.step(dict(valid=True,avatar_valid=True,avatar_y=c['avatar_template'][1],rope_valid=True,rope_y=.28),.04)
  self.assertFalse(c['visible_trial_coherent'])

class FragmentTests(unittest.TestCase):
 def setUp(self):
  self.c,self.m,_=load(ROOT);self.v,_=local_motion_components(ROOT,self.c,self.m);self.f=self.m.FragmentTracker()
 def frame(self,y,both=True):
  c=self.c;l,t,r,b=c['roi'];im=np.zeros((500,600),np.uint8)
  for xa,xb in [(.487,.505)]+([(.625,.643)] if both else []):
   cv2.line(im,(round((xa-l)/(r-l)*600),round((y-t)/(b-t)*500)),(round((xb-l)/(r-l)*600),round((y-t)/(b-t)*500)),35,2)
  return im
 def test_dim_gray_broken_rope_bridges_center(self):
  im=self.frame(.3);o=self.f.detect(im,np.uint8(im>0)*255,self.c,.565,0)
  self.assertIsNotNone(o);self.assertEqual(o['visible_sides'],2);self.assertAlmostEqual(o['rope_y'],.3,delta=.006)
 def test_one_side_requires_recent_full_shape_and_expires(self):
  im=self.frame(.3,False);motion=np.uint8(im>0)*255
  self.assertIsNone(self.f.detect(im,motion,self.c,.565,0))
  full=self.frame(.3);o=self.f.detect(full,np.uint8(full>0)*255,self.c,.565,0);self.f.accept(o,0)
  im=self.frame(.32,False);o=self.f.detect(im,np.uint8(im>0)*255,self.c,.565,.06)
  self.assertIsNotNone(o);self.assertTrue(o['shape_projected']);self.assertAlmostEqual(o['rope_y'],.32,delta=.006)
  self.assertIsNone(self.f.detect(im,np.uint8(im>0)*255,self.c,.565,.14))
 def test_static_geometry_unlocks_even_with_nearby_motion(self):
  im=self.frame(.3)
  for i in range(20):
   o=self.f.detect(im,np.uint8(im>0)*255,self.c,.565,i*.02)
   if o:o=self.f.accept(o,i*.02)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['rope_rejection'],'stationary_geometry')

 def test_low_rope_changing_tilt_is_not_static_background(self):
  for i in range(20):
   slope=.3*np.sin(i*.3);xs=np.array([.49,.51,.62,.64]);ys=.55+slope*(xs-.565)
   o=dict(rope_valid=True,rope_y=.55,rope_slope=float(slope),rope_curvature=0,rope_points=np.column_stack([xs,ys]).tolist())
   o=self.f.accept(o,i*.02)
   self.assertTrue(o['rope_valid'])
 def test_accelerating_visible_trajectory_is_not_rejected_as_noise(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m);p=cls(c)
  p.samples.extend([(0,.27),(.02,.28)])
  p.step(dict(valid=True,avatar_valid=True,avatar_y=c['avatar_template'][1],rope_valid=True,rope_y=.304),.04)
  self.assertTrue(c['visible_trial_coherent'])
 def test_projection_tracks_motion_prediction_at_high_speed(self):
  for tm,y in [(0,.3),(.02,.34)]:
   im=self.frame(y);o=self.f.detect(im,np.uint8(im>0)*255,self.c,.565,tm);self.assertIsNotNone(o);self.f.accept(o,tm)
  im=self.frame(.42,False);o=self.f.detect(im,np.uint8(im>0)*255,self.c,.565,.06)
  self.assertIsNotNone(o);self.assertTrue(o['shape_projected'])

 def test_acceleration_fit_uses_recent_observations(self):
  c,m,_=load(ROOT);v,cls=local_motion_components(ROOT,c,m);p=cls(c)
  p.samples.extend([(0,.2),(.02,.20),(.04,.2),(.06,.22),(.08,.26),(.1,.30)])
  position,speed,error=p.fit()
  self.assertAlmostEqual(position,.30);self.assertAlmostEqual(speed,2);self.assertLess(error,.006)

class SlowArrivalTests(unittest.TestCase):
 def controller(self):
  c,m,_=load(ROOT);_,cls=local_motion_components(ROOT,c,m)
  c.update(experimental_input=True,demonstration_crossing_trial=True,pulse_seconds=.035)
  c['calibration'].update(danger_y=.57,input_latency_seconds=.06,safe_airborne_seconds=.20,rotation_direction=1,max_prediction_error=.012)
  p=cls(c);p.tracking_established=True;p.ground_count=3;p.low_swing=True
  return c,p
 def step_at(self,p,c,t,y,speed,down=False):
  p.samples.clear();p.samples.extend([(t-.04,y-speed*.04),(t-.02,y-speed*.02)])
  return p.step(dict(valid=True,rope_valid=True,rope_y=y,avatar_valid=True,avatar_y=c['avatar_template'][1]),t,down)
 def test_slow_approach_does_not_jump_in_old_wide_height_band(self):
  c,p=self.controller();d=self.step_at(p,c,1,.4,.20)
  self.assertFalse(d['down']);self.assertEqual(d['input_inhibited'],'slow_waiting_for_feet')
 def test_slow_waits_until_arrival_is_close(self):
  c,p=self.controller();d=self.step_at(p,c,1,.54,.20)
  self.assertFalse(d['down']);d=self.step_at(p,c,1.02,.554,.20)
  self.assertTrue(d['down']);self.assertEqual(d['trigger'],'slow_feet_arrival_trial')
 def test_upward_approach_also_triggers(self):
  c,p=self.controller();d=self.step_at(p,c,1,.584,-.20)
  self.assertTrue(d['down'])
 def test_one_pass_no_duplicate_and_rearm_only_after_actual_crossing(self):
  c,p=self.controller();self.step_at(p,c,1,.554,.20)
  p.jump_sent_at=None
  d=self.step_at(p,c,1.02,.558,.20);self.assertFalse(d['down'])
  self.step_at(p,c,1.04,.590,.20);self.assertFalse(p.slow_consumed)
  d=self.step_at(p,c,1.06,.584,-.20);self.assertTrue(d['down'])
 def test_stale_airborne_and_judgment_never_input(self):
  c,p=self.controller();c['experimental_input']=False
  self.assertFalse(self.step_at(p,c,1,.554,.20)['down'])
  c['experimental_input']=True;p.ground_count=0
  self.assertFalse(self.step_at(p,c,1.02,.558,.20)['down'])

 def test_slow_occlusion_does_not_restore_wide_band_trigger(self):
  c,p=self.controller();p.samples.extend([(.94,.388),(.96,.392),(.98,.396)])
  d=p.step(dict(valid=False,rope_valid=False,avatar_valid=True,avatar_y=c['avatar_template'][1]),1)
  self.assertFalse(d['down']);self.assertEqual(d['input_inhibited'],'slow_waiting_for_feet')
 def test_slow_occlusion_prediction_is_short_and_once(self):
  c,p=self.controller();p.samples.extend([(.94,.542),(.96,.546),(.98,.550)])
  d=p.step(dict(valid=False,rope_valid=False,avatar_valid=True,avatar_y=c['avatar_template'][1]),1)
  self.assertTrue(d['down']);self.assertEqual(d['trigger'],'slow_feet_prediction_trial')
  p.jump_sent_at=None
  d=p.step(dict(valid=False,rope_valid=False,avatar_valid=True,avatar_y=c['avatar_template'][1]),1.02)
  self.assertFalse(d['down'])

 def test_normal_rotation_does_not_use_slow_lead(self):
  results=[]
  for lead in (.06,.12):
   c,p=self.controller();p.low_swing=False;c['slow_arrival']['lead_seconds']=lead
   results.append(self.step_at(p,c,1,.4,.20))
  self.assertEqual(results[0]['down'],results[1]['down'])
  self.assertEqual(results[0].get('trigger'),results[1].get('trigger'))
  self.assertEqual(results[0].get('trigger'),'demonstration_crossing_trial')
 def test_rearm_observed_outside_slow_speed_range(self):
  c,p=self.controller();self.step_at(p,c,1,.554,.20);p.jump_sent_at=None
  self.step_at(p,c,1.02,.610,1.0)
  self.assertFalse(p.slow_consumed)
  d=self.step_at(p,c,1.04,.618,-.6)
  self.assertTrue(d['down']);self.assertEqual(d['trigger'],'slow_feet_arrival_trial')
 def test_confirmed_pass_can_reverse_without_large_endpoint_clearance(self):
  c,p=self.controller();self.step_at(p,c,1,.554,.20);p.jump_sent_at=None
  self.step_at(p,c,1.02,.578,.20)
  self.assertTrue(p.slow_crossed);self.assertTrue(p.slow_consumed)
  d=self.step_at(p,c,1.04,.580,-.20)
  self.assertTrue(d['down'])
 def test_low_mode_latches_and_three_overhead_frames_restore_rotation(self):
  c,p=self.controller();p.low_swing=False
  o=dict(valid=True,rope_valid=True,rope_y=.60,avatar_valid=True,avatar_y=c['avatar_template'][1],motion_mode_candidate='low_swing')
  p.step(o,1);self.assertTrue(p.low_swing)
  for i in range(3):p.step(dict(o,rope_y=.30,motion_mode_candidate=None),1.02+i*.02)
  self.assertFalse(p.low_swing)
