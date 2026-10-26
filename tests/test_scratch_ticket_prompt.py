import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.visual_features import extract
from modular_agent.domains.hololive_dreams.states import classify,UIState
from modular_agent.agent.daily_tasks import DailyTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

class ScratchTicketTests(unittest.TestCase):
 def test_real_screenshot_recognizes_scratch_word_with_e(self):
  path=ROOT/'domains/hololive_dreams/data/world_reference/20261022/codex-clipboard-09ae474c-9d87-4d32-b3eb-ad261aba4735.png'
  img=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
  features=extract(img,(0,0),ROOT)
  self.assertTrue(features['wheel_prompt'])
  r=report();r.frame['world_features']=features
  self.assertEqual(classify(r).state,UIState.INTERACTION)
  # Label alone must not authorize an E interaction.
  img[448:497,790:834]=0
  self.assertFalse(extract(img,(0,0),ROOT)['wheel_prompt'])
 def test_wheel_branch_uses_e_without_legacy_template_or_walking(self):
  c=Computer();near=report('menu','stage');near.frame['world_features']={'wheel_prompt':True,'hud_count':3}
  frames=iter([near]*4+[report('daily_rewards_get')]+[near]*3)
  t=DailyTasks(config(),lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  t.gift('wheel')
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['e'])
 def test_gift_branch_does_not_treat_scratch_as_npc_gift(self):
  c=Computer();near=report('menu','stage');near.frame['world_features']={'wheel_prompt':True,'hud_count':3}
  cfg=config();cfg['nearby_walk_max_seconds']=.3
  t=DailyTasks(cfg,lambda:near,c,lambda _:None,clock=lambda:c.seconds)
  with self.assertRaisesRegex(RuntimeError,'未找到礼物'):t.gift('the_cell')
  self.assertFalse(any(a.name=='press' and a.arguments['key']=='e' for a in c.actions))

if __name__=='__main__':unittest.main()
