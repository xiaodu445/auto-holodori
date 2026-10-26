import unittest
from collections import deque
from test_jump_rope_temporal_recovery import bank as source
from modular_agent.realtime.acceleration_evidence_bank import AccelerationEvidenceBank
from modular_agent.realtime.coexisting_stage_bank import CoexistingStageBank

class AccelerationPolicyTests(unittest.TestCase):
 def models(self,entering=True,duration=.4,fps=40):
  old=source();b=AccelerationEvidenceBank(dict(old.c,guard_speed_commits=True,acceleration_evidence_policy=True),old.boundary,.4,dict(stages=old.profiles));b.acquire(.3,.01,1)
  a=next(p for p in b.items if p.key==b.active);a.gear=1 if entering else 2
  p=b.make(a.mode,a.phase,2 if entering else 1,parent=a.key);b.items=[a,p]
  times=[i/fps for i in range(round(duration*fps)+1)];b.time=times[-1];a.visual=p.visual=True
  b.evidence={a.key:deque((t,.5,True) for t in times),p.key:deque((t,.7,True) for t in times)};b.speed_evidence={k:deque(v) for k,v in b.evidence.items()}
  return b,a,p
 def cue(self,b):b.speed_audio_hint=dict(time=b.time,motion_hint='accelerate',distance=.15,margin=.1)
 def test_short_burst_cannot_exit_acceleration(self):
  b,a,p=self.models(False,.18);self.cue(b);self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_continuous_normal_evidence_can_exit(self):
  b,a,p=self.models(False,.4);self.cue(b);self.assertTrue(b.speed_commit_support(a,p,b.time))
 def test_audio_does_not_enter_without_visual_pairs(self):
  b,a,p=self.models(True,.2);self.cue(b);b.speed_evidence[p.key]=deque([(b.time,.9,True)])
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_matching_cue_allows_shorter_confirmed_entry(self):
  b,a,p=self.models(True,.15);self.cue(b);self.assertTrue(b.speed_commit_support(a,p,b.time));self.assertEqual(b.acceleration_review['required_span'],.12)
 def test_wrong_or_future_audio_never_authorizes(self):
  b,a,p=self.models(True,.15);self.cue(b);b.speed_audio_hint['time']+=.1;self.assertIsNone(b.reliable_acceleration(b.time))
  b.speed_audio_hint.update(time=b.time,motion_hint='decelerate');self.assertIsNone(b.reliable_acceleration(b.time))
 def test_cue_does_not_overrule_strong_normal_visual_evidence(self):
  b,a,p=self.models(False,.4);self.cue(b);self.assertTrue(b.speed_commit_support(a,p,b.time))
 def test_prune_preserves_only_bounded_cue_candidate_and_its_clock(self):
  b,a,p=self.models();b.time=2.;p.born=0.;phase=p.phase
  b.audio_candidates={p.key:dict(expires=2.5,mode=p.mode,stage=0,cue_time=1.)};b.prune()
  self.assertIn(p,b.items);self.assertEqual(p.phase,phase)
  b.time=2.6;b.prune();self.assertNotIn(p,b.items)
 def test_commit_retains_cue_backed_runner_without_retaining_every_old_role(self):
  b,a,p=self.models();self.cue(b);b.audio_candidates={p.key:dict(expires=2.,mode=p.mode,stage=0,cue_time=0.)}
  q=b.make(a.mode,a.phase,0);b.items.append(q)
  b.resolve_speed_commit(p,a,b.time,'test');self.assertEqual({x.key for x in b.items},{a.key,p.key});self.assertEqual(b.last_speed_commit['retained_audio_candidates'],[p.key])
 def test_low_mode_is_not_changed_by_acceleration_guard(self):
  b,a,p=self.models();p.mode='low_swing';self.assertTrue(b.speed_commit_support(a,p,b.time))
 def test_retained_candidate_does_not_chase_incumbent_phase(self):
  b,a,p=self.models();b.audio_candidates={p.key:dict(expires=2.,mode=p.mode,stage=0,cue_time=0.)}
  before=(p.phase,p.speed);b.correct(p,.05,.02,.9,.4);self.assertEqual(before,(p.phase,p.speed))
 def test_reliable_cue_keeps_existing_candidate_without_forcing_selection(self):
  b,a,p=self.models();self.cue(b);key=a.key;phase=p.phase;b.advance(b.time+.01)
  self.assertIn(p.key,b.audio_candidates);self.assertEqual(b.active,key)
  self.assertNotEqual(p.phase,phase)
 def test_weak_cue_cannot_create_protected_candidate(self):
  b,a,p=self.models();self.cue(b);b.speed_audio_hint['distance']=.25;b.advance(b.time+.01)
  self.assertEqual(b.audio_candidates,{})
 def test_no_reliable_cue_preserves_legacy_support_rule(self):
  b,a,p=self.models(False,.18);self.assertTrue(b.speed_commit_support(a,p,b.time));self.assertIsNone(b.acceleration_review)
 def test_terminal_stage_not_affected(self):
  b,a,p=self.models(False,.18);b.item_stages[a.key]=b.item_stages[p.key]=4;self.cue(b)
  expected=CoexistingStageBank.speed_commit_support(b,a,p,b.time)
  self.assertEqual(b.speed_commit_support(a,p,b.time),expected);self.assertIsNone(b.acceleration_review)
 def test_protected_audio_entry_uses_short_paired_confirmation(self):
  b,a,p=self.models(True,.15);b.c['half_cycle_switch_policy']=True;self.cue(b)
  b.audio_candidates={p.key:dict(expires=2.,mode=p.mode,stage=0,cue_time=0.)}
  a.score=.5;p.score=.52;phase=p.phase
  b.choose(b.time,.025)
  self.assertEqual(b.active,p.key);self.assertEqual(p.phase,phase)
 def test_invalid_flag_rejected(self):
  b=source()
  with self.assertRaises(ValueError):AccelerationEvidenceBank(dict(b.c,acceleration_evidence_policy='yes'),b.boundary,.4,dict(stages=b.profiles))

if __name__=='__main__':unittest.main()
