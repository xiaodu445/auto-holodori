import unittest
import copy
import numpy as np
from modular_agent.realtime.jump_rope_preview import render_frame

class PreviewRenderingTests(unittest.TestCase):
    def test_relative_coordinates_and_no_mutation(self):
        image=np.zeros((200,200,3),np.uint8)
        config=dict(roi=[.3,.1,.7,.5],avatar_template=[.54,.448,.58,.518])
        observation=dict(rope_points=[[.4,.3],[.5,.3],[.6,.3]],rope_valid=True,rope_y=.3,arrow_position=[.5,.2])
        before=copy.deepcopy(observation)
        rendered=render_frame(image,observation,dict(state='grounded',mode='rotation'),config,60)
        self.assertEqual(rendered.shape,(417,200,3))
        self.assertTrue(np.any(rendered[95:106,45:56]))
        self.assertFalse(image.any())
        self.assertEqual(observation,before)
    def test_missing_rope_does_not_invent_visible_curve(self):
        image=np.zeros((200,200,3),np.uint8)
        config=dict(roi=[0,0,1,1],avatar_template=[.54,.448,.58,.518])
        rendered=render_frame(image,dict(rope_valid=False,rope_points=[]),dict(prediction=dict(historical=True,rope_y=.2)),config,50)
        self.assertTrue(np.any(rendered[35:46,108:119]))
        # Prediction is red, not the cyan fitted-observation line.
        self.assertFalse(np.any((rendered[:200,:,0]>0)&(rendered[:200,:,1]>0)&(rendered[:200,:,2]==0)))
