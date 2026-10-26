"""B019: GET followed by an actor-independent, slightly scaled RANK UP."""
import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.agent.daily_tasks import DailyTasks
from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks
from modular_agent.domains.hololive_dreams.visual_features import extract
from modular_agent.domains.hololive_dreams.states import classify,UIState
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

def rank():
 r=report();r.frame['world_features']={'rank_up':True};return r

class RankOverlayTests(unittest.TestCase):
 def flow(self,frames):
  self.c=Computer();it=iter(frames)
  d=DailyTasks(config(),lambda:next(it),self.c,lambda _:None,clock=lambda:self.c.seconds)
  d.report=report();return ClaimTasks(d)
 def test_get_then_rank_then_parent(self):
  f=self.flow([report('daily_rewards_get'),rank(),rank(),rank(),report('claim_achievement_page'),report('claim_achievement_page')])
  f.claim(report('claim_one').knowledge_matches[0])
  self.assertEqual(f.claims,1)
  # One claim, one GET close, and at least one rank close; never repeats claim.
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),3)
 def test_rank_then_get_then_parent_also_supported(self):
  f=self.flow([rank(),report('daily_rewards_get'),report('daily_rewards_get'),report('daily_rewards_get'),report('claim_achievement_page'),report('claim_achievement_page')])
  f.claim(report('claim_one').knowledge_matches[0]);self.assertEqual(f.claims,1)
 def test_page_wait_closes_both_overlays(self):
  f=self.flow([report('daily_rewards_get'),rank(),report('claim_achievement_page')])
  f.page('achievement_page')
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),2)
 def test_unknown_gap_does_not_count_as_confirmed_parent(self):
  parent=report('claim_achievement_page')
  f=self.flow([rank(),parent,report(),parent,rank(),parent,parent])
  f.claim(report('claim_one').knowledge_matches[0]);self.assertEqual(f.claims,1)
 def test_real_screenshot_at_recorded_window_geometry(self):
  path=ROOT/'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-ad755308-f1cd-43b3-84fd-5c71affc19a0.png'
  image=cv2.imdecode(np.fromfile(str(path),np.uint8),1)[161:,470:]
  # Screenshot cuts off right/bottom; retain log-confirmed 1280x757 geometry.
  # Missing edges are neutral fixture padding, never treated as observed evidence.
  canvas=np.full((757,1280,3),240,np.uint8)
  canvas[:image.shape[0],:image.shape[1]]=image
  features=extract(canvas,(0,0),ROOT)
  self.assertGreater(features['scores']['rank_title'],.88)
  self.assertTrue(features['rank_up'])
  r=report();r.frame['world_features']=features
  self.assertEqual(classify(r).state,UIState.RANK_UP)

if __name__=='__main__':unittest.main()
