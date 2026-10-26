"""B022: input delivery does not prove an enabled claim was accepted."""
import unittest
from unittest.mock import Mock
from modular_agent.agent.daily_tasks import DailyTasks
from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config

def enabled(x=1100):
 r=report('claim_all','claim_one')
 for m in r.knowledge_matches:
  m['claim_enabled']=True;m['bounds']['x']=x
  m['bounds']['y']=660 if m['label']=='claim_all' else 300
 return r

class ClaimRetryTests(unittest.TestCase):
 def flow(self,observe):
  self.c=Computer()
  self.d=DailyTasks(config(),lambda:observe(),self.c,lambda _:None,clock=lambda:self.c.seconds)
  self.d.report=enabled();return ClaimTasks(self.d)
 def test_dropped_first_click_can_retry_with_fresh_evidence(self):
  reward_frames=[0]
  def observe():
   clicks=sum(a.name=='click' for a in self.c.actions)
   if clicks==1:return enabled()
   if reward_frames[0]==0:
    reward_frames[0]+=1;return report('daily_rewards_get')
   return report('claim_achievement_page')
  f=self.flow(observe);f.claim(enabled().knowledge_matches[0])
  self.assertEqual(f.claims,1)
  clicks=[a for a in self.c.actions if a.name=='click']
  self.assertEqual(len(clicks),3) # initial, justified retry, reward dismissal
 def test_unchanged_enabled_button_retries_at_most_twice(self):
  f=self.flow(lambda:enabled())
  with self.assertRaisesRegex(RuntimeError,'未确认完整奖励'):f.claim(enabled().knowledge_matches[0])
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),3)
 def test_disabled_does_not_retry(self):
  r=enabled()
  for m in r.knowledge_matches:m['claim_enabled']=False
  f=self.flow(lambda:r)
  with self.assertRaises(RuntimeError):f.claim(enabled().knowledge_matches[0])
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),1)
 def test_moved_button_does_not_retry(self):
  f=self.flow(lambda:enabled(1130))
  with self.assertRaises(RuntimeError):f.claim(enabled().knowledge_matches[0])
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),1)
 def test_no_retry_after_any_reward_was_seen(self):
  first=[True]
  def observe():
   if first[0]:first[0]=False;return report('daily_rewards_get')
   return enabled()
  f=self.flow(observe)
  with self.assertRaises(RuntimeError):f.claim(enabled().knowledge_matches[0])
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),2)
 def test_detail_waits_for_position_to_settle(self):
  frames=iter([enabled(1110),enabled(1100),enabled(1100)])
  f=self.flow(lambda:next(frames));f.claim=Mock()
  self.assertTrue(f.achievement_detail());f.claim.assert_called_once()
  self.assertEqual(f.claim.call_args.args[0]['bounds']['x'],1100)

if __name__=='__main__':unittest.main()
