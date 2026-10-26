import json
from pathlib import Path
from collections import deque
import unittest
from modular_agent.realtime.coexisting_stage_bank import CoexistingStageBank
ROOT=Path(__file__).resolve().parents[1]
def bank():
 c=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_stage_coexist_config.json').read_text())
 a=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/stage_clock_library_v2_trial.json').read_text())
 return CoexistingStageBank(c,.4140625,.4,a)
class CoexistTests(unittest.TestCase):
 def test_hint_preserves_active_speed_phase_warp_and_bounds(self):
  b=bank();b.set_stage(1,0);b.acquire(.3,.01,-1);a=next(p for p in b.items if p.key==b.active)
  state=(a.phase,a.speed,a.warp,b.bounds(a));b.set_stage(2,.02)
  self.assertEqual(state,(a.phase,a.speed,a.warp,b.bounds(a)))
  self.assertEqual((b.count_stage_index,b.stage_index),(2,1))
  self.assertTrue(all(b.item_stage(p)==2 for p in b.items if p.key in b.stage_candidates))
 def test_prune_keeps_pending_stage_evidence_and_same_gear(self):
  b=bank();b.acquire(.3,.01,1);b.set_stage(1,.02);p=next(p for p in b.items if p.key in b.stage_candidates and p.gear==1)
  b.evidence[p.key]=deque([(.01,.8,True)]);b.prune()
  self.assertIn(p,b.items);self.assertEqual(len(b.evidence[p.key]),1)
 def test_no_visual_support_keeps_old_stage(self):
  b=bank();b.acquire(.3,.01,1);key=b.active;b.set_stage(1,.02);b.advance(.03);b.choose(.03,.02)
  self.assertEqual(b.active,key);self.assertEqual(b.stage_index,0)
 def test_temporal_evidence_can_switch_without_skill_end_event(self):
  b=bank();b.acquire(.3,.01,1);b.set_stage(1,.02);a=next(p for p in b.items if p.key==b.active);p=next(p for p in b.items if p.key in b.stage_candidates and p.gear==1)
  b.time=.18;a.visual=True;a.score=.5;p.visual=True;p.score=.8
  times=[.03,.06,.09,.12,.15,.18];b.evidence[a.key]=deque((t,.5,True) for t in times);b.evidence[p.key]=deque((t,.8,True) for t in times)
  b.choose(.18,.02);self.assertEqual(b.active,p.key);self.assertEqual(b.stage_index,1)
