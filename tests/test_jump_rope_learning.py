import unittest
from modular_agent.realtime.learn_jump_rope import features,metrics
import numpy as np

class TimingLearningTests(unittest.TestCase):
    def row(self,t,y):return dict(t=t,rope_valid=True,avatar_valid=True,rope_y=y,avatar_y=.45)
    def test_features_use_only_past_and_restart_after_loss(self):
        first=[self.row(i*.02,.3+i*.01) for i in range(5)]
        prefix=features(first)
        extended=features(first+[self.row(.12,.7),self.row(1,.4)])
        self.assertEqual(extended[:len(prefix)],prefix)
        self.assertAlmostEqual(prefix[-1][1][1],.5)
        self.assertFalse(any(t==1 for t,_ in extended))
    def test_metrics_expose_false_positive_and_missed_frames(self):
        result=metrics(np.array([.9,.8,.2,.1]),np.array([1,0,1,0]),.5)
        self.assertEqual(result['precision'],.5)
        self.assertEqual(result['recall'],.5)
        self.assertEqual(result['false_positive_frames'],1)
        self.assertEqual(result['missed_positive_frames'],1)
