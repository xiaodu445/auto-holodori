"""B018: unknown notification rows are not an empty list or a dead end."""
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.agent.daily_tasks import DailyTasks
from modular_agent.domains.hololive_dreams.daily_plan import build_plan
from modular_agent.domains.hololive_dreams.visual_features import extract
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

class NotificationPolicyTests(unittest.TestCase):
 def tree(self,policy='ignore_run',rows=1):
  self.c=Computer();cfg=config();cfg['notification_scroll_pages']=2
  free=report('menu','stage','attention')
  panel=report();panel.frame['world_features']={'notification_panel':True,'notification_rows':rows}
  def observe():
   clicks=sum(a.name=='click' for a in self.c.actions)
   return panel if clicks==1 else free
  t=DailyTasks(cfg,observe,self.c,lambda _:None,clock=lambda:self.c.seconds,selected_tasks=['wheel'],unknown_notification_policy=policy)
  return t
 def test_ignore_exits_and_does_not_reopen_in_same_run(self):
  t=self.tree();r=t.notifications()
  self.assertEqual(r['outcome'],'success');self.assertTrue(r['stage_complete'])
  self.assertTrue(r['badge_ignored']);self.assertEqual(r['ignore_scope'],'run')
  self.assertFalse(r['verified']);self.assertFalse(r['rewards_verified'])
  self.assertEqual(r['items']['wheel']['outcome'],'skipped')
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),2)
  previous=len(self.c.actions);self.assertIs(t.notifications(),r)
  self.assertEqual(len(self.c.actions),previous)
  self.assertTrue(self.c.released)
 def test_stop_policy_preserves_unknown_panel(self):
  t=self.tree('stop');r=t.notifications()
  self.assertEqual(r['outcome'],'unknown');self.assertIn('stop',r['message'])
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),1)
 def test_empty_panel_not_marked_as_ignored_badge(self):
  r=self.tree(rows=0).notifications()
  self.assertEqual(r['outcome'],'success');self.assertFalse(r['badge_ignored'])
 def test_known_notice_below_unknown_row_still_runs(self):
  t=self.tree();original=t.observe
  def observe():
   r=original()
   if any(a.name=='scroll' for a in self.c.actions) and sum(a.name=='click' for a in self.c.actions)==1:
    return report('daily_notice_wheel')
   return r
  t.observe=observe;t.gift=Mock()
  r=t.notifications();self.assertEqual(r['outcome'],'success');t.gift.assert_called_once_with('wheel')
 def test_new_run_has_no_inherited_ignore(self):
  self.assertIsNone(self.tree().notification_run_result)
  self.tree().notifications()
  self.assertIsNone(self.tree().notification_run_result)
 def test_missing_panel_evidence_still_stops(self):
  t=self.tree();t.observe=lambda:report('menu','stage','attention')
  self.assertEqual(t.notifications()['outcome'],'unknown')
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),1)
 def test_plan_policy_override(self):
  self.assertEqual(build_plan(config())['unknown_notification_policy'],'ignore_run')
  self.assertEqual(build_plan(config(),{'unknown_notification_policy':'stop'})['unknown_notification_policy'],'stop')
  with self.assertRaises(ValueError):build_plan(config(),{'unknown_notification_policy':'forever'})
 def test_reported_screenshot_has_one_unknown_row(self):
  p=ROOT/'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-c41c3b2f-099e-42df-9dbb-b9ee3482e020.png'
  img=cv2.imdecode(np.fromfile(str(p),np.uint8),1)
  # Desktop screenshot; user game begins here and is clipped at the right edge.
  features=extract(img[166:,429:],(429,166),ROOT)
  self.assertTrue(features['notification_panel']);self.assertEqual(features['notification_rows'],1)

if __name__=='__main__':unittest.main()
