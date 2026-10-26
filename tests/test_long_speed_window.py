import unittest
from types import SimpleNamespace
from modular_agent.realtime.coexisting_stage_bank import CoexistingStageBank

class LongWindowTests(unittest.TestCase):
    def setup_bank(self,times,candidate=.9,rival=.65):
        b=object.__new__(CoexistingStageBank)
        a=SimpleNamespace(key=1,speed=1.,mode='rotation_forward',role='normal')
        p=SimpleNamespace(key=2,speed=1.2,mode='rotation_forward',role='accelerate')
        q=SimpleNamespace(key=3,speed=1.,mode='rotation_forward',role='normal')
        b.items=[a,p,q];b.role=lambda p:p.role
        b.evidence={1:[(t,.5,True) for t in times],2:[(t,candidate,True) for t in times],3:[(t,rival,True) for t in times]}
        return b,a,p
    def test_short_burst_cannot_confirm_even_if_many_frames(self):
        b,a,p=self.setup_bank([i*.01 for i in range(14)])
        assert not b.long_speed_support(a,p,.13)
        assert 'evidence_window_incomplete' in b.last_speed_review['reasons']
    def test_ambiguous_roles_do_not_confirm(self):
        b,a,p=self.setup_bank([i*.02 for i in range(26)],candidate=.8,rival=.79)
        assert not b.long_speed_support(a,p,.5)
        assert 'role_candidates_ambiguous' in b.last_speed_review['reasons']
    def test_sustained_distinct_support_confirms(self):
        b,a,p=self.setup_bank([i*.02 for i in range(26)])
        assert b.long_speed_support(a,p,.5)
        assert b.last_speed_review['required_span']>=.25
