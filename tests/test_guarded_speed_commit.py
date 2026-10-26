import unittest
from collections import deque
from test_jump_rope_temporal_recovery import bank

class GuardedCommitTests(unittest.TestCase):
 def models(self,stage=2,from_gear=0,to_gear=2,times=None):
  b=bank();b.c['guard_speed_commits']=True;b.set_stage(stage,0);b.acquire(.3,.01,1)
  a=next(p for p in b.items if p.key==b.active);a.gear=from_gear;a.speed=b.rates(stage)['rotation_gears'][from_gear]
  p=b.make(a.mode,a.phase,to_gear,parent=a.key);b.items=[a,p]
  times=times or [i*.02 for i in range(26)];b.time=times[-1]
  b.speed_evidence={a.key:deque((t,.5,True) for t in times),p.key:deque((t,.8,True) for t in times)}
  return b,a,p
 def test_short_error_burst_cannot_commit(self):
  b,a,p=self.models(times=[i*.01 for i in range(19)])
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_missing_incumbent_pairs_cannot_borrow_candidate_span(self):
  b,a,p=self.models();b.speed_evidence[a.key]=deque([(b.time,.5,True)])
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_runner_is_compared_at_identical_times(self):
  b,a,p=self.models();q=b.make(a.mode,a.phase,1);b.items.append(q)
  b.speed_evidence[q.key]=deque((t,.795,True) for t,_,_ in b.speed_evidence[p.key])
  self.assertFalse(b.speed_commit_support(a,p,b.time))
  self.assertIn('competing_clock_ambiguous',b.last_speed_review['reasons'])
 def test_distinct_continuous_visual_evidence_can_commit_without_audio(self):
  b,a,p=self.models();self.assertTrue(b.speed_commit_support(a,p,b.time))
 def test_audio_does_not_force_commit(self):
  b,a,p=self.models(times=[i*.01 for i in range(15)]);b.speed_audio_hint=dict(time=b.time,motion_hint='accelerate',distance=.1,margin=.1)
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_wrong_or_future_audio_does_not_shorten_window(self):
  b,a,p=self.models(times=[i*.02 for i in range(12)])
  for cue in [dict(time=b.time,motion_hint='decelerate',distance=.1,margin=.1),dict(time=b.time+.1,motion_hint='accelerate',distance=.1,margin=.1)]:
   b.speed_audio_hint=cue;self.assertFalse(b.speed_commit_support(a,p,b.time));self.assertEqual(b.last_speed_review['required_span'],.30)
 def test_near_identical_nominal_roles_remain_guarded_after_rate_adaptation(self):
  b,a,p=self.models(stage=4,from_gear=1,to_gear=2,times=[i*.01 for i in range(15)]);a.speed*=.94
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_winner_evidence_survives_cohort_cleanup(self):
  b,a,p=self.models();b.evidence=b.speed_evidence.copy();b.resolve_speed_commit(a,p,b.time,'test')
  self.assertEqual(len(b.last_speed_commit['paired_evidence']),26);self.assertEqual(b.items,[p]);self.assertEqual(b.evidence,{})

 def test_direct_acceleration_to_deceleration_is_also_guarded(self):
  b,a,p=self.models(from_gear=2,to_gear=0,times=[i*.01 for i in range(15)])
  self.assertFalse(b.speed_commit_support(a,p,b.time))
 def test_low_mode_rules_do_not_borrow_circle_guard(self):
  b,a,p=self.models();p.mode='low_swing'
  self.assertTrue(b.speed_commit_support(a,p,b.time))
 def test_matching_audio_only_shortens_valid_paired_confirmation(self):
  b,a,p=self.models(times=[i*.02 for i in range(12)]);b.speed_audio_hint=dict(time=b.time,motion_hint='accelerate',distance=.1,margin=.1)
  self.assertTrue(b.speed_commit_support(a,p,b.time));self.assertEqual(b.last_speed_review['required_span'],.18)
 def test_disabled_guard_preserves_legacy_short_windows(self):
  b,a,p=self.models(times=[i*.01 for i in range(3)]);b.c['guard_speed_commits']=False
  self.assertTrue(b.speed_commit_support(a,p,b.time))
