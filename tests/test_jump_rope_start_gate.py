import unittest
import numpy as np
import cv2
from modular_agent.realtime.jump_rope_start_gate import GoStartGate,waiting_observation

class StartGateTests(unittest.TestCase):
    def test_stays_closed_for_static_scene_and_countdown(self):
        gate=GoStartGate();image=np.zeros((360,640,3),np.uint8)
        cv2.rectangle(image,(300,120),(320,180),(0,255,255),-1)
        for t in range(10):self.assertFalse(gate.update(image,t))
        self.assertEqual(waiting_observation()['whole_curve'],[])
    def test_requires_confirmed_banner_then_clear_and_latches(self):
        gate=GoStartGate();blank=np.zeros((360,640,3),np.uint8);go=blank.copy()
        cv2.rectangle(go,(280,130),(355,165),(0,255,255),-1)
        self.assertFalse(gate.update(go,1));self.assertFalse(gate.update(blank,2))
        for t in [3,4,5]:self.assertFalse(gate.update(go,t))
        self.assertFalse(gate.update(blank,6));self.assertFalse(gate.update(blank,7))
        self.assertTrue(gate.update(blank,8));self.assertEqual(gate.started_at,8)
        self.assertTrue(gate.update(go,9))
