import unittest
from modular_agent.realtime.build_jump_rope_swing_rates import crossings
from modular_agent.realtime.phase_evidence import ClockRateEvidence

class CrossingTests(unittest.TestCase):
    def rows(self):return [dict(time=t,center_y=y,fit_support=.8,template_error=.001) for t,y in [(0,.4),(.1,.6),(.2,.7)]]
    def test_crossing_uses_only_bracketed_values(self):
        self.assertEqual(crossings(self.rows(),.8,0,.2),[])
        self.assertAlmostEqual(crossings(self.rows(),.5,0,.2)[0],.05)
    def test_long_missing_interval_not_interpolated(self):
        rows=self.rows();rows[1]['time']=.5
        self.assertEqual(crossings(rows[:2],.5,0,.6),[])

class ClockRateTests(unittest.TestCase):
    def test_positive_clock_estimated_with_quantization_noise(self):
        chain=ClockRateEvidence(.3,.7,max_gap=.65);result=None
        for i in range(25):result=chain.update((.95+.5*i*.025+(i%2)*.003)%1,i*.025,1)
        self.assertIsNotNone(result);self.assertAlmostEqual(result['rate'],.5,delta=.015)
    def test_static_or_jump_is_not_a_valid_rate(self):
        chain=ClockRateEvidence(.3,.7);result=None
        for i in range(25):result=chain.update(.3,i*.025,1)
        self.assertIsNone(result)
        self.assertIsNone(chain.update(.8,.65,1))
