import unittest
from unittest.mock import patch
from modular_agent.agent.daily_tasks import DailyTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config

class TransferRecoveryTests(unittest.TestCase):
 def tree(self,frames):
  c=Computer();it=iter(frames)
  return DailyTasks(config(),lambda:next(it),c,lambda _:None,clock=lambda:c.seconds),c
 def test_no_lever_no_input(self):
  t,c=self.tree([]);t.recover_transfer('wheel',report('menu','stage'))
  self.assertEqual(c.actions,[])
 def test_switch_then_replay_fresh_notice(self):
  lever=report('entry_lever_interact');free=report('menu','stage')
  notice=report('daily_notice_wheel')
  t,c=self.tree([free,free,free,free])
  def transition(**kwargs):t.report=notice;return notice
  t.transition=transition;t.report=lever
  decisions=[{'state':'lever_interact','action':'press','key':'e','duration':.08},
   {'state':'switch_casino','action':'click','target':notice.knowledge_matches[0]},
   {'state':'free_main'},{'state':'free_main'}]
  with patch('modular_agent.domains.hololive_dreams.entry_flow.GreedCardsEntry.decide',side_effect=decisions):
   t.recover_transfer('wheel',lever)
  clicks=[a for a in c.actions if a.name=='click']
  self.assertEqual(len(clicks),2)
 def test_stuck_lever_bounded(self):
  lever=report('entry_lever_interact');c=Computer()
  t=DailyTasks(config(),lambda:lever,c,lambda _:None,clock=lambda:c.seconds);t.report=lever
  with patch('modular_agent.domains.hololive_dreams.entry_flow.GreedCardsEntry.decide',return_value={'state':'lever_interact','action':'press','key':'e','duration':.08}):
   with self.assertRaisesRegex(RuntimeError,'未确认完成'):t.recover_transfer('wheel',lever)
  self.assertEqual(len([a for a in c.actions if a.name=='press']),3)
 def test_cancel_zero_input(self):
  t,c=self.tree([]);c.stopped=True
  with self.assertRaises(RuntimeError):t.recover_transfer('wheel')
  self.assertEqual(c.actions,[])
