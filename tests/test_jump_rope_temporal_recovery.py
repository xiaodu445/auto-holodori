import unittest
from collections import deque
from test_jump_rope_stage_coexist import bank as source_bank
from modular_agent.realtime.evidence_recovery_bank import EvidenceRecoveryBank

def bank():
 b=source_bank();return EvidenceRecoveryBank(b.c,b.boundary,.4,dict(stages=b.profiles))
class RecoveryTests(unittest.TestCase):
 def setup_models(self):
  b=bank();b.acquire(.3,.01,1);b.set_stage(1,.02)
  a=next(p for p in b.items if p.key==b.active);p=next(p for p in b.items if p.key in b.stage_candidates and p.gear==1)
  b.time=.18;a.visual=True;a.score=.5;p.visual=True;p.score=.54
  times=[.03,.06,.09,.12,.15,.18];b.evidence[a.key]=deque((t,.5,True) for t in times);b.evidence[p.key]=deque((t,.54,True) for t in times)
  return b,a,p
 def test_strong_stage_evidence_purges_old_stage(self):
  b,a,p=self.setup_models();phase=p.phase;b.choose(.18,.02)
  self.assertEqual(b.active,p.key);self.assertEqual(p.phase,phase);self.assertEqual(b.items,[p]);self.assertEqual(b.stage_index,1)
 def test_one_high_score_frame_does_not_force_stage(self):
  b,a,p=self.setup_models();b.evidence[p.key]=deque([(.18,.95,True)]);p.score=.95;b.choose(.18,.02)
  self.assertEqual(b.active,a.key)
 def test_without_current_visual_evidence_incumbent_continues(self):
  b,a,p=self.setup_models();p.visual=False;b.choose(.18,.02);self.assertEqual(b.active,a.key)

 def test_small_advantage_does_not_prematurely_upgrade_stage(self):
  b,a,p=self.setup_models();p.score=.515;b.evidence[p.key]=deque((t,.515,True) for t in [.03,.06,.09,.12,.15,.18])
  b.choose(.18,.02);self.assertEqual(b.active,a.key)

 def test_same_stage_speed_window_can_adopt_below_instantaneous_margin(self):
  b=bank();b.set_stage(1,0);b.acquire(.3,.01,-1);a=next(p for p in b.items if p.key==b.active)
  p=b.make(a.mode,a.phase,2,parent=a.key);b.items.append(p);b.landing_number=1;b.branch_info[p.key]=dict(landing=1,time=.03,epoch=b.epoch)
  b.time=.18;a.visual=True;a.score=.5;p.visual=True;p.score=.515
  times=[.03,.06,.09,.12,.15,.18];b.evidence[a.key]=deque((t,.5,True) for t in times);b.evidence[p.key]=deque((t,.515,True) for t in times)
  phase=p.phase;b.choose(.18,.02);self.assertEqual(b.active,p.key);self.assertEqual(p.phase,phase)

 def test_half_cycle_policy_follows_signed_clock_for_both_directions(self):
  b=bank();b.c['half_cycle_switch_policy']=True
  for mode,direction in [('rotation_forward',1),('rotation_reverse',-1)]:
   p=b.make(mode,b.boundary+direction*.2,1);q=b.make(mode,p.phase,2)
   self.assertEqual(b.switch_requirements(p,q),(.025,.18,8))
   p.phase=b.boundary+direction*.7
   self.assertEqual(b.switch_requirements(p,q),(.005,.12,6))
 def test_early_half_rejects_weak_window_even_if_basic_branch_supported(self):
  b=bank();b.c['half_cycle_switch_policy']=True;b.set_stage(1,0);b.acquire(.3,.01,-1)
  a=next(p for p in b.items if p.key==b.active);a.phase=b.boundary-.2
  p=b.make(a.mode,a.phase,2,parent=a.key);b.items.append(p);b.branch_info[p.key]=dict(landing=1,time=.03,epoch=b.epoch);b.landing_number=1;b.time=.24
  times=[.03,.06,.09,.12,.15,.18,.21,.24];b.evidence[a.key]=deque((t,.5,True) for t in times);b.evidence[p.key]=deque((t,.52,True) for t in times)
  self.assertFalse(b.legal_successor(a,p,.24));a.phase=b.boundary-.7;p.phase=a.phase
  self.assertTrue(b.legal_successor(a,p,.24))
