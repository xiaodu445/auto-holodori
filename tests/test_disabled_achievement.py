"""B021: blue disabled buttons and startup recovery from achievement pages."""
import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.perception.general import GeneralVision
from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks,templates_for
from modular_agent.agent.daily_tasks import DailyTasks
from modular_agent.agent.startup_tree import StartupTree
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

class DisabledAchievementTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  v=GeneralVision.for_project(ROOT,'hololive_dreams',enable_ocr=False,enable_uia=False,enable_cv_buttons=False)
  cls.frames=[]
  for source in ('6146cf02-e410-424f-b3c7-e38f16d06f05','94f74b1d-4c99-426c-90a4-ad05cbf5988a'):
   p=ROOT/f'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-{source}.png'
   img=cv2.imdecode(np.fromfile(str(p),np.uint8),1)
   if source.startswith('6146'):img=img[6:,280:]
   r=v.analyze(img,environment='hololive_dreams',template_names=templates_for('achievements'),template_threshold=.92)
   r.frame['target_window_handle']=7;r.windows=[{'handle':7,'foreground':True}]
   cls.frames.append(r)
  v.close()
 def test_disabled_button_is_detected_but_never_enabled(self):
  r=self.frames[0]
  self.assertTrue(r.frame['world_features']['achievement_detail'])
  matches=[m for m in r.knowledge_matches if m['label']=='claim_all']
  self.assertTrue(matches);self.assertFalse(any(m['claim_enabled'] for m in matches))
 def test_no_available_text_for_empty_bottom_row(self):
  r=self.frames[1];matches=[m for m in r.knowledge_matches if m['label']=='claim_available']
  self.assertEqual(len(matches),4)
  self.assertFalse(any(m['bounds']['y']>640 for m in matches))
 def test_empty_detail_exits_without_click(self):
  c=Computer();frames=iter([self.frames[0],self.frames[0],self.frames[1]])
  d=DailyTasks(config(),lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  self.assertFalse(ClaimTasks(d).achievement_detail())
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['escape'])
  self.assertFalse(any(a.name=='click' for a in c.actions))
 def test_startup_uses_back_not_blind_center_on_both_pages(self):
  for r in self.frames:
   r.frame['startup_template_only']=True
   self.assertEqual(StartupTree().decide(r)['action'],'back')
 def test_startup_returns_through_parent_with_zero_clicks(self):
  from test_connected_agent import Computer as StartupComputer
  free=report('menu','stage');free.frame['world_features']={'hud_count':4}
  free.frame['startup_template_only']=True
  frames=iter([*self.frames,free,free]);c=StartupComputer()
  result=StartupTree().run(lambda:next(frames),c,lambda _:None)
  self.assertEqual(result['outcome'],'success')
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['escape','escape'])
  self.assertFalse(any(a.name=='click' for a in c.actions))

if __name__=='__main__':unittest.main()
