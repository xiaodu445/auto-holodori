import unittest
from collections import deque
from modular_agent.realtime.terminal_stage_bank import TerminalStageBank
from test_jump_rope_temporal_recovery import bank as source_bank

class TerminalStageTests(unittest.TestCase):
 def bank(self):
  b=source_bank();return TerminalStageBank(dict(b.c,terminal_stage_strategy=True),b.boundary,.4,dict(stages=b.profiles))
 def locked_models(self):
  b=self.bank();b.set_stage(4,0);b.acquire(.3,.01,1);a=next(p for p in b.items if p.gear==1);b.active=a.key
  b.terminal_locked=True;b.terminal_requested=True
  p=b.make(a.mode,a.phase,2,parent=a.key);b.items=[a,p];b.time=.8;a.visual=p.visual=True
  return b,a,p
 def test_stage_four_uses_same_existing_strategy(self):
  b=self.bank();b.set_stage(3,0);b.acquire(.3,.01,1);a=b.choose(.01,0)
  self.assertFalse(b.terminal_requested);self.assertFalse(b.terminal_locked);self.assertEqual(b.item_stage(a),3)
 def test_final_hint_preserves_current_skill_until_speed_confirmed(self):
  b=self.bank();b.set_stage(3,0);b.acquire(.3,.01,-1);a=next(p for p in b.items if p.key==b.active);before=(a.phase,a.speed,a.warp)
  b.set_stage(4,.02);b.choose(.02,.01)
  self.assertTrue(b.terminal_requested);self.assertFalse(b.terminal_locked);self.assertEqual((a.phase,a.speed,a.warp),before)
 def test_only_actual_final_speed_confirmation_locks_policy(self):
  b=self.bank();b.set_stage(4,0);b.acquire(.3,.01,1);b.choose(.01,0)
  self.assertTrue(b.terminal_locked);self.assertEqual(b.terminal_started_at,.01)
  self.assertFalse(b.set_stage(3,.02));self.assertEqual(b.count_stage_index,4)
 def test_complete_occlusion_cannot_switch_speed(self):
  b,a,p=self.locked_models();times=[i*.02 for i in range(41)]
  b.terminal_evidence={a.key:deque((t,.05,False) for t in times),p.key:deque((t,.05,False) for t in times)}
  self.assertFalse(b.terminal_support(a,p,.8))
 def test_visible_evidence_on_both_sides_of_gap_can_confirm(self):
  b,a,p=self.locked_models();times=[i*.02 for i in range(41)]
  b.terminal_evidence={a.key:deque((t,.5 if t<.2 or t>.6 else .05,t<.2 or t>.6) for t in times),p.key:deque((t,.85 if t<.2 or t>.6 else .05,t<.2 or t>.6) for t in times)}
  self.assertTrue(b.terminal_support(a,p,.8));self.assertLess(b.terminal_review['observable_pairs'],len(times))
 def test_competing_roles_must_be_separable(self):
  b,a,p=self.locked_models();q=b.make(a.mode,a.phase,0);b.items.append(q);times=[i*.02 for i in range(41)]
  b.terminal_evidence={a.key:deque((t,.5,True) for t in times),p.key:deque((t,.8,True) for t in times),q.key:deque((t,.795,True) for t in times)}
  self.assertFalse(b.terminal_support(a,p,.8));self.assertIn('fixed_roles_ambiguous',b.terminal_review['reasons'])
 def test_prune_keeps_three_fixed_roles_across_long_occlusion(self):
  b,a,p=self.locked_models();q=b.make(a.mode,a.phase,0);b.items.append(q);b.time=10.;b.prune()
  self.assertEqual({x.gear for x in b.items},{0,1,2});self.assertEqual({b.item_stage(x) for x in b.items},{4})
 def test_speed_commit_does_not_erase_other_fixed_clocks(self):
  b,a,p=self.locked_models();times=[i*.02 for i in range(41)];b.terminal_evidence={a.key:deque((t,.5,True) for t in times),p.key:deque((t,.8,True) for t in times)}
  before=list(b.items);b.record_terminal_commit(a,p,.8)
  self.assertEqual(b.items,before);self.assertEqual(len(b.last_speed_commit['paired_evidence']),41)
 def test_reset_clears_final_stage_and_audio_context(self):
  b,a,p=self.locked_models();b.reset();self.assertFalse(b.terminal_locked);self.assertFalse(b.terminal_requested);self.assertEqual(b.terminal_evidence,{})

 def test_uncalibrated_deceleration_stays_diagnostic(self):
  b,a,p=self.locked_models();q=b.make(a.mode,a.phase,0);b.items.append(q);b.c['uncalibrated_decelerate_diagnostic_only']=True
  self.assertFalse(b.legal_successor(a,q,b.time))
