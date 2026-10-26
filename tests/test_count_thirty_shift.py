import unittest
from unittest.mock import patch
import numpy as np
import test_acceleration_evidence_policy as fixture
from modular_agent.realtime.jump_rope_count_hint import CountThirtyShift,digit_shapes

class CountThirtyTests(unittest.TestCase):
 def test_preserves_role_direction_coordinate_and_cannot_revert(self):
  for direction in (1,-1):
   for gear in (0,1,2):
    b,a,p=fixture.AccelerationPolicyTests().models();a.mode='rotation_forward' if direction>0 else 'rotation_reverse';a.gear=gear;a.warp=b.profile_warp(a.mode,gear)
    coordinate=a.coordinate;key=a.key;epoch=b.epoch
    self.assertTrue(b.force_count_stage(2,b.time));self.assertEqual(a.key,key);self.assertEqual(a.direction,direction);self.assertEqual(a.gear,gear);self.assertEqual(b.epoch,epoch)
    self.assertAlmostEqual(a.coordinate%1,coordinate%1,places=6);self.assertEqual(b.item_stage(a),2);self.assertEqual(a.speed,b.rates(2)['rotation_gears'][gear]);self.assertEqual(b.items,[a])
    b.advance(b.time+.02);self.assertEqual(b.stage_index,2);self.assertFalse(b.force_count_stage(2,b.time))
 def test_low_swing_preserves_episode_and_phase(self):
  b,a,p=fixture.AccelerationPolicyTests().models();a.mode='low_swing';a.gear=0;phase=a.phase
  b.force_count_stage(2,b.time);self.assertEqual(a.phase,phase);self.assertEqual(a.mode,'low_swing');self.assertEqual(a.speed,b.rates(2)['swing_gears'][0])
 def test_does_not_downgrade_later_stage(self):
  b,a,p=fixture.AccelerationPolicyTests().models();b.force_count_stage(3,b.time);self.assertFalse(b.force_count_stage(2,b.time));self.assertEqual(b.stage_index,3)
 def test_triggers_once_only_on_confirmed_count(self):
  shift=CountThirtyShift({'digits':{}});bank=unittest.mock.Mock();bank.force_count_stage.return_value=True
  with patch.object(shift.counter,'update',side_effect=[None,1,None,2,None,3]):
   for now in range(6):shift.update(None,now,bank)
  bank.force_count_stage.assert_called_once_with(2,3)
 def test_capture_roi_matches_full_client_glyphs(self):
  import cv2
  image=np.zeros((1000,1600,3),np.uint8);cv2.rectangle(image,(60,80),(105,190),(255,255,255),-1)
  full=digit_shapes(image);local=digit_shapes(image[20:720,16:1408],(.01,.02,.88,.72))
  self.assertEqual(len(full),1);self.assertEqual(len(local),1);self.assertTrue(np.array_equal(full[0],local[0]))
