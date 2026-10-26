import unittest
from modular_agent.realtime.phase_evidence import PhaseEvidenceChain

class IndependentEvidenceTests(unittest.TestCase):
    def test_stationary_high_score_cannot_win_rotating_chain(self):
        chain=PhaseEvidenceChain(.6,1.6);result=None
        for i in range(12):result=chain.update([(.4,1.),((.1+.75*i*.04)%1,.7)],i*.04,1)
        self.assertIsNotNone(result);self.assertAlmostEqual(result['rate'],.75,places=6)
    def test_reverse_crosses_phase_zero_and_rejects_jumps(self):
        chain=PhaseEvidenceChain(.6,1.6);result=None
        for i in range(12):result=chain.update([((.1-1.1*i*.04)%1,.8),((i*.37)%1,1.)],i*.04,-1)
        self.assertIsNotNone(result);self.assertAlmostEqual(result['rate'],1.1,delta=.04)
    def test_new_direction_discards_old_chains(self):
        chain=PhaseEvidenceChain(.6,1.6)
        for i in range(8):chain.update([(.1+i*.04,.9)],i*.04,1)
        self.assertIsNone(chain.update([(.4,.9)],.32,-1))
