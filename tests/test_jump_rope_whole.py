import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.jump_rope import load,whole_rope_components,run_jump_rope
from modular_agent.realtime.jump_rope_preview import render_frame
ROOT=Path(__file__).resolve().parents[1]

class WholeRopeTests(unittest.TestCase):
 def setUp(self):
  self.c,self.m,_=load(ROOT);self.c['whole_shape_model']=True;self.v,self.cls=whole_rope_components(ROOT,self.c,self.m)
  l,t,r,b=self.c['roi'];self.cw=500/(r-l);self.ch=300/(b-t)
  self.anchors=[np.array([(.231-l)*self.cw,(.557-t)*self.ch]),np.array([(.819-l)*self.cw,(.397-t)*self.ch])]
  info=[dict(point=[.231,.557],source='measured',confidence=1),dict(point=[.819,.397],source='measured',confidence=1)]
  self.v._anchors=lambda *args:(self.anchors,info)
 def frame(self,amplitude,gap=False):
  im=np.zeros((300,500,3),np.uint8);curve=self.v._seed(self.anchors,amplitude,self.cw,self.ch)
  for i in range(1,41):
   if gap and 17<=i<=23:continue
   cv2.line(im,tuple(np.rint(curve[i-1]).astype(int)),tuple(np.rint(curve[i]).astype(int)),(85,85,85),3)
  return im
 def test_gray_curve_tracks_both_anchors_and_parametric_points(self):
  for i in range(5):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  self.assertTrue(o['rope_valid'],o)
  self.assertEqual(len(o['whole_curve']),41)
  self.assertEqual(len(o['whole_point_states']),41)
  self.assertAlmostEqual(o['whole_curve'][0][0],.231,delta=.003)
  self.assertAlmostEqual(o['whole_curve'][-1][0],.819,delta=.003)
 def test_occluded_points_are_never_marked_measured(self):
  for i in range(4):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  o=self.v.detect(self.frame(.34,True),.08)
  self.assertTrue(o['whole_curve'])
  self.assertTrue(any(x!='measured' for x in o['whole_point_states'][18:22]))
 def test_static_scene_does_not_acquire_a_rope(self):
  for i in range(5):o=self.v.detect(self.frame(.30),i*.02)
  self.assertFalse(o['rope_valid'])
 def test_gap_clears_optical_flow_and_stale_history(self):
  for i in range(4):self.v.detect(self.frame(.30+i*.01),i*.02)
  o=self.v.detect(self.frame(.4),1)
  self.assertEqual(o['flow_points'],0);self.assertFalse(o['rope_valid'])
 def test_judgment_and_api_reject_live_inputs(self):
  p=self.cls(self.c);self.assertFalse(p.step(dict(rope_valid=True),0,True)['down'])
  with self.assertRaisesRegex(ValueError,'judgment-only'):
   run_jump_rope(ROOT,None,0,live=True,whole_rope=True)
 def test_preview_does_not_connect_unknown_gap(self):
  o=dict(whole_curve=[[.3,.3],[.4,.3],[.5,.3]],whole_point_states=['measured','unknown','measured'],rope_valid=False)
  im=render_frame(np.zeros((100,200,3),np.uint8),o,{},self.c,60)
  self.assertEqual(im.shape,(317,200,3))

 def test_resize_resets_optical_flow(self):
  for i in range(4):self.v.detect(self.frame(.30+i*.01),i*.02)
  o=self.v.detect(cv2.resize(self.frame(.35),(400,240)),.08)
  self.assertEqual(o['flow_points'],0)
 def test_long_occlusion_does_not_keep_old_curve_indefinitely(self):
  for i in range(4):self.v.detect(self.frame(.30+i*.01),i*.02)
  for i in range(4,20):o=self.v.detect(np.zeros((300,500,3),np.uint8),i*.02)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['whole_curve'],[])
 def test_window_change_resets_judgment_safely(self):
  p=self.cls(self.c);p.reset_motion();self.assertEqual(p.state,'recovering')
  d=p.step(dict(rope_valid=True),0,True,frame_age=.1)
  self.assertFalse(d['down']);self.assertEqual(d['state'],'stale')

 def test_cli_rejects_every_input_flag_before_desktop_access(self):
  from unittest.mock import patch
  from modular_agent.realtime import jump_rope
  for flag in ('--live','--experimental-live','--test-space'):
   with patch('sys.argv',['jump_rope','--whole-rope',flag]),patch.object(jump_rope,'ActionComputer') as computer:
    with self.assertRaises(SystemExit):jump_rope.main()
    computer.assert_not_called()

 def test_all_candidates_reject_teleports_before_state_update(self):
  old=self.v._seed(self.anchors,.3,self.cw,self.ch)
  self.v.curve=old.copy();self.v.velocity=np.zeros_like(old);self.v.old_time=1
  self.assertFalse(self.v._continuous(old+np.array([0,self.ch*.15]),1.02,self.cw,self.ch))
  self.assertTrue(np.array_equal(self.v.curve,old))
 def test_fast_but_predicted_motion_is_allowed(self):
  old=self.v._seed(self.anchors,.3,self.cw,self.ch)
  self.v.curve=old.copy();self.v.velocity=np.tile([0,self.ch*2],(41,1));self.v.old_time=1
  candidate=old+self.v.velocity*.02
  self.assertTrue(self.v._continuous(candidate,1.02,self.cw,self.ch))
 def test_low_confidence_fit_does_not_contaminate_velocity_or_confirmation(self):
  for i in range(5):self.v.detect(self.frame(.30+i*.01),i*.02)
  self.assertIsNotNone(self.v.curve)
  velocity=self.v.velocity.copy();confirmed=self.v.confirmed_time
  prediction=self.v.curve+self.v.velocity*.02
  self.v._fit_candidate=lambda *args:None
  o=self.v.detect(self.frame(.35),.10)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['tracking_status'],'predicting')
  self.assertTrue(np.allclose(velocity,self.v.velocity));self.assertEqual(confirmed,self.v.confirmed_time)
  self.assertTrue(np.allclose(prediction,self.v.curve))
 def test_acquisition_requires_three_consistent_candidates(self):
  for i in range(3):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['whole_curve'],[])
  o=self.v.detect(self.frame(.33),.06)
  self.assertTrue(o['rope_valid']);self.assertEqual(o['track_id'],1)
 def test_abrupt_different_curve_cannot_replace_existing_track(self):
  for i in range(5):old=self.v.detect(self.frame(.30+i*.01),i*.02)
  o=self.v.detect(self.frame(-.15),.10)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['track_id'],old['track_id'])
  if o['whole_curve']:
   jump=np.linalg.norm(np.array(o['whole_curve'])-np.array(old['whole_curve']),axis=1)
   self.assertLess(float(np.quantile(jump,.95)),.04)

 def test_reversed_velocity_exceeds_acceleration_gate(self):
  old=self.v._seed(self.anchors,.3,self.cw,self.ch)
  self.v.curve=old.copy();self.v.velocity=np.tile([0,self.ch*2],(41,1));self.v.old_time=1
  self.assertFalse(self.v._continuous(old-self.v.velocity*.02,1.02,self.cw,self.ch))
 def test_reacquired_curve_has_new_identity(self):
  for i in range(5):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  first=o['track_id']
  for i in range(5,16):o=self.v.detect(np.zeros((300,500,3),np.uint8),i*.02)
  self.assertEqual(o['whole_curve'],[])
  for i in range(16,22):o=self.v.detect(self.frame(.30+(i-16)*.01),i*.02)
  self.assertTrue(o['rope_valid']);self.assertGreater(o['track_id'],first)
 def test_invalid_continuity_limits_are_rejected(self):
  from modular_agent.realtime.jump_rope import load_image
  reference=load_image(ROOT/'domains/hololive_dreams/data/jump_rope_samples/reference.png')[21:]
  for key,value in [('max_speed',0),('max_acceleration',float('nan')),('position_noise',-.01)]:
   c=dict(self.c,whole_continuity={key:value})
   with self.assertRaises(ValueError):type(self.v)(c,reference)

 def test_one_visible_side_can_correct_recent_curve_without_measuring_hidden_side(self):
  for i in range(5):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  first=o['track_id'];im=self.frame(.35)
  # Cover most of the left half; keep a spread-out right fragment.
  im[:,:290]=0
  o=self.v.detect(im,.10)
  self.assertTrue(o['rope_valid'],o);self.assertEqual(o['track_id'],first)
  self.assertTrue(o['whole_curve'])
  self.assertTrue(all(state!='measured' for state in o['whole_point_states'][2:20]))

 def test_partial_support_cannot_renew_full_shape_prior(self):
  for i in range(5):o=self.v.detect(self.frame(.30+i*.01),i*.02)
  full_time=self.v.full_confirmed_time
  for i in range(5,14):
   im=self.frame(.30+i*.01);im[:,:290]=0
   o=self.v.detect(im,i*.02)
  self.assertEqual(self.v.full_confirmed_time,full_time)
  self.assertFalse(o['rope_valid'])

 def test_shape_fit_rejects_zigzag_measurements(self):
  raw=self.v._seed(self.anchors,.3,self.cw,self.ch)
  raw[2:-2,1]+=np.where(np.arange(37)%2,1,-1)*self.ch*.04
  observed=np.ones(41,dtype=bool);observed[[0,-1]]=False
  info=[{'source':'measured'},{'source':'measured'}]
  self.assertIsNone(self.v._fit_shape(raw,observed,False,self.anchors,info,self.cw,self.ch))
 def test_shape_fit_resists_local_blocker_points(self):
  original=self.v._seed(self.anchors,.3,self.cw,self.ch);raw=original.copy();raw[10:16,1]+=self.ch*.07
  observed=np.ones(41,dtype=bool);observed[[0,-1]]=False
  info=[{'source':'measured'},{'source':'measured'}]
  fit=self.v._fit_shape(raw,observed,False,self.anchors,info,self.cw,self.ch)
  self.assertIsNotNone(fit)
  self.assertLess(float(np.median(np.linalg.norm((fit[0]-original)/[self.cw,self.ch],axis=1))),.008)
  self.assertFalse(np.any(fit[2][10:16]))
 def test_static_rope_near_animation_is_not_acquired(self):
  for i in range(12):
   im=self.frame(.3);cv2.circle(im,(210+i%4,110),6,(180,180,180),-1)
   o=self.v.detect(im,i*.02)
  self.assertFalse(o['rope_valid'])

 def test_batched_evidence_matches_scalar(self):
  gray=cv2.cvtColor(self.frame(.30),cv2.COLOR_BGR2GRAY)
  edges=cv2.Canny(gray,25,70);distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
  seeds=[(self.v._seed(self.anchors,a,self.cw,self.ch),False) for a in (.2,.3,.4)]
  expected=[self.v._evidence(seed,distance,distance,gray,self.cw,self.ch,flag) for seed,flag in seeds]
  self.v._prepare_evidence(seeds,distance,distance,gray,self.cw,self.ch)
  for (seed,flag),old in zip(seeds,expected):
   actual=self.v._evidence(seed,distance,distance,gray,self.cw,self.ch,flag)
   for a,b in zip(actual,old):self.assertTrue(np.allclose(a,b))

 def test_shape_profile_is_opt_in(self):
  c,m,_=load(ROOT);v,_=whole_rope_components(ROOT,c,m)
  self.assertFalse(v.c['whole_shape_model'])
 def test_shape_requires_whole_rope(self):
  with self.assertRaisesRegex(ValueError,'requires whole-rope'):
   run_jump_rope(ROOT,None,0,whole_shape=True)
