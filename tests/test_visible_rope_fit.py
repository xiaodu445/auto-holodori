import unittest
import numpy as np
from types import SimpleNamespace
from dataclasses import replace
from test_jump_rope_temporal_recovery import bank
from modular_agent.realtime.visible_rope_fit import VisibleRopeFit

class VisibleFitTests(unittest.TestCase):
 def models(self,direction=1):
  b=bank();b.set_stage(2,0);b.acquire(.30,.01,direction);a=next(p for p in b.items if p.key==b.active);return b,a
 def fit(self,x,trusted=True):return dict(coordinate=x,quality=.8,coverage=.8,moving=.4,margin=.1,trusted=trusted)
 def test_large_phase_error_waits_for_coherent_recovery_window(self):
  b,a=self.models();a.phase+=.2;f=VisibleRopeFit();before=a.phase
  self.assertFalse(f.update(b,a,self.fit(.3),.02));self.assertEqual(a.phase,before);self.assertEqual(f.review['path'],'recovery_pending')
  for i in range(1,6):f.update(b,a,self.fit(.3+a.speed*i*.025),.02+i*.025)
  self.assertTrue(f.review['phase_applied']);self.assertEqual(f.review['path'],'recovery');self.assertAlmostEqual(a.coordinate,.3+a.speed*5*.025,places=5)
 def test_small_error_uses_bounded_correction_not_snap(self):
  b,a=self.models();f=VisibleRopeFit();target=(a.coordinate+.02)%1;before=a.phase
  self.assertTrue(f.update(b,a,self.fit(target),.02,dt=.02));self.assertEqual(f.review['path'],'gentle');self.assertLessEqual(abs(a.phase-before),b.c['max_phase_correction']);self.assertGreater(abs(a.coordinate-target),.001)
 def test_untrusted_fragment_does_not_move_clock(self):
  b,a=self.models();phase=a.phase;f=VisibleRopeFit();self.assertFalse(f.update(b,a,self.fit(.8,False),.02));self.assertEqual(a.phase,phase)
 def test_long_visible_speed_overrides_wrong_gear_in_both_directions(self):
  for direction in (1,-1):
   b,a=self.models(direction);truth=replace(a,gear=2,speed=b.rates(2)['rotation_gears'][2],warp=b.profile_warp(a.mode,2));truth.phase=VisibleRopeFit.clock(b,truth,.3)
   a.gear=1;a.warp=b.profile_warp(a.mode,1);f=VisibleRopeFit()
   for i in range(19):
    now=.02+i*.025;truth.phase=VisibleRopeFit.clock(b,truth,.3)+direction*truth.speed*i*.025
    f.update(b,a,self.fit(truth.coordinate),now)
   self.assertTrue(f.review['speed_applied'],f.review);self.assertEqual(a.gear,2);self.assertAlmostEqual(a.speed,truth.speed,places=5);self.assertEqual(a.direction,direction)
 def test_one_frame_cannot_change_speed(self):
  b,a=self.models();gear=a.gear;f=VisibleRopeFit();f.update(b,a,self.fit(a.coordinate+.01),.02);self.assertEqual(a.gear,gear);self.assertEqual(f.review['reason'],'collecting_visible_speed_window')
 def test_long_gap_discards_old_speed_evidence(self):
  b,a=self.models();f=VisibleRopeFit();f.update(b,a,self.fit(.3),.02);f.update(b,a,None,.12);self.assertEqual(len(f.records),0);f.update(b,a,self.fit(.4),.13);self.assertEqual(len(f.records),1)
 def test_episode_change_discards_old_evidence(self):
  b,a=self.models();f=VisibleRopeFit();f.update(b,a,self.fit(.3),.02);b.epoch+=1;f.update(b,a,self.fit(.4),.04);self.assertEqual(len(f.records),1)
 def test_scene_or_ambiguous_image_is_rejected(self):
  v=SimpleNamespace(grid=np.arange(96)/96,reference_curves=np.zeros((96,41,2)))
  table=dict(indices=np.arange(96),q=np.full(96,.7),coverage=np.full(96,.8),moving=np.full(96,.3),raw=np.zeros((96,41,2)),seen=np.ones((96,41),bool))
  support=lambda *args:np.ones(41,bool)
  self.assertFalse(VisibleRopeFit.select(v,table,support)['trusted']);self.assertIsNone(VisibleRopeFit.select(v,table,support,scene=True))
 def test_low_swing_preserves_direction_episode_and_phase_branch(self):
  b,a=self.models();a.mode='low_swing';a.gear=0;a.warp=b.warp;a.phase=.65;episode=b.low_episode;f=VisibleRopeFit()
  f.update(b,a,self.fit(a.coordinate+.01),.02,dt=.02);self.assertLess(a.coordinate_velocity,0);self.assertEqual(b.low_episode,episode);self.assertEqual(f.review['path'],'gentle')

 def test_recent_visual_speed_blocks_conflicting_candidate_even_with_audio(self):
  b,a=self.models();b.c['visible_fragment_priority']=True;b.c['guard_speed_commits']=True
  p=b.make(a.mode,a.phase,2,parent=a.key);b.items.append(p)
  b.visible_speed_authority=dict(time=.1,epoch=b.epoch,mode=a.mode,stage=b.item_stage(a),gear=a.gear)
  b.speed_audio_hint=dict(time=.12,motion_hint='accelerate',distance=.1,margin=.2)
  self.assertFalse(b.speed_commit_support(a,p,.15));self.assertIn('trusted_visible_speed_has_priority',b.last_speed_review['reasons'])
 def test_visual_priority_does_not_block_motion_mode_change(self):
  b,a=self.models();b.c['visible_fragment_priority']=True;b.c['guard_speed_commits']=True
  p=b.make('low_swing',.4,0,parent=a.key)
  b.visible_speed_authority=dict(time=.1,epoch=b.epoch,mode=a.mode,stage=b.item_stage(a),gear=a.gear)
  self.assertTrue(b.speed_commit_support(a,p,.15))
 def test_near_identical_gears_do_not_receive_arbitrary_label(self):
  from unittest.mock import patch
  b,a=self.models();f=VisibleRopeFit();base=b.rates(2)['rotation_gears'][1]
  with patch.object(b,'profile_warp',return_value=None),patch.object(b,'rates',return_value=dict(rotation_gears=[base*.7,base,base*1.02],swing_gears=[.4])):
   for i in range(19):f.update(b,a,self.fit((.3+base*i*.025)%1),.02+i*.025)
  self.assertTrue(f.review['speed_applied']);self.assertFalse(f.review['gear_confirmed']);self.assertEqual(f.review['reason'],'trusted_visible_rate_gear_unresolved')

 def test_measured_rate_can_override_nominal_prior_without_inventing_gear(self):
  from unittest.mock import patch
  b,a=self.models();b.c['visible_fragment_priority']=True;f=VisibleRopeFit();initial=a.gear
  with patch.object(b,'profile_warp',return_value=None):
   for i in range(19):f.update(b,a,self.fit((.3+.70*i*.025)%1),.02+i*.025)
  self.assertTrue(f.review['speed_applied']);self.assertFalse(f.review['gear_confirmed']);self.assertEqual(a.gear,initial);self.assertAlmostEqual(a.speed,.70,places=5);self.assertLess(b.bounds(a)[0],.70);self.assertGreater(b.bounds(a)[1],.70)
