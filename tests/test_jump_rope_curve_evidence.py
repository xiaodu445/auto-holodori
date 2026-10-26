import unittest
import numpy as np
from modular_agent.realtime.curve_evidence import coherent_offsets

class CoherentEvidenceTests(unittest.TestCase):
    def test_fragmented_distractor_does_not_replace_smooth_strip(self):
        cost=np.full((1,20,5),10.);cost[0,:,2]=1.
        for i in range(20):cost[0,i,0 if i%2 else 4]=0.
        result=coherent_offsets(cost,np.arange(5),1.)
        self.assertTrue(np.all(result==2))
    def test_occluded_gap_bridges_without_forced_jump(self):
        cost=np.full((1,12,5),10.);cost[0,:,3]=0.;cost[0,4:8]=0.
        self.assertTrue(np.all(coherent_offsets(cost,np.arange(5))==3))
    def test_curves_independent_and_gradual_offset_allowed(self):
        cost=np.full((2,8,5),10.)
        wanted=np.array([[0,0,1,1,2,2,3,3],[4,4,4,4,4,4,4,4]])
        for r in range(2):cost[r,np.arange(8),wanted[r]]=0.
        np.testing.assert_array_equal(coherent_offsets(cost,np.arange(5)),wanted)
