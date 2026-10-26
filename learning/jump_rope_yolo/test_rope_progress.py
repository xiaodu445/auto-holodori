import unittest
from types import SimpleNamespace
from game_jump_logic import RopeProgress
class ProgressTests(unittest.TestCase):
 def run_cycles(self,nodes,cycles):
  p=RopeProgress();t=SimpleNamespace(key='test',period=1.,data={'jump_progress_nodes':nodes})
  for i in range(cycles*100+1):p.update(i/100,dict(phase=(i/100)%1,status='observed'),t)
  return p
 def test_normal_one_per_cycle(self):self.assertEqual(self.run_cycles([.25],12).count,12)
 def test_low_swing_two_per_cycle(self):self.assertEqual(self.run_cycles([.25,.75],12).count,24)
 def test_stage5_locks(self):
  p=self.run_cycles([.25],80);self.assertEqual(p.stage,5)
 def test_lost_and_reanchor_do_not_add_crossing(self):
  p=RopeProgress();t=SimpleNamespace(key='test',period=1.,data={'jump_progress_nodes':[.25]})
  p.update(0,dict(phase=.1,status='observed'),t)
  p.update(.02,dict(phase=.4,status='observed'),t)
  self.assertEqual(p.count,0)
  p.update(.04,dict(phase=.42,status='lost'),t)
  p.update(.06,dict(phase=.6,status='observed'),t)
  self.assertEqual(p.count,0)
if __name__=='__main__':unittest.main()
