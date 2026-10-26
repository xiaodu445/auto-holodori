import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.visual_features import extract
from modular_agent.domains.hololive_dreams.states import classify,UIState
from modular_agent.domains.hololive_dreams.scratch_ticket import ScratchTicket
from modular_agent.agent.daily_tasks import DailyTasks
from modular_agent.agent.startup_tree import StartupTree
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

def scratch():
 r=report();r.frame['world_features']={'scratch_ticket':True,'anchors':{'scratch_open':{'score':.99,'bounds':dict(x=575,y=628,width=102,height=26)}}}
 return r

class ScratchOpenTests(unittest.TestCase):
 def test_real_image_and_missing_prompt_negative(self):
  path=ROOT/'domains/hololive_dreams/data/world_reference/20261025/codex-clipboard-1655f28b-bb1f-4cb7-8273-2900900abaff.png'
  img=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
  f=extract(img,(0,0),ROOT);self.assertTrue(f['scratch_ticket'])
  r=report();r.frame['world_features']=f
  self.assertEqual(classify(r).state,UIState.SCRATCH_TICKET)
  img[620:663,560:690]=0
  self.assertFalse(extract(img,(0,0),ROOT)['scratch_ticket'])
 def test_dropped_click_retries_only_three_times(self):
  controller=ScratchTicket();click=Mock()
  for now in (0,.3,1,2,2.5,4,6,10):controller.update(scratch(),click,now)
  self.assertEqual(click.call_count,3)
 def test_no_prompt_no_input_and_delayed_prompt_works(self):
  controller=ScratchTicket();click=Mock()
  controller.update(report(),click,0);click.assert_not_called()
  controller.update(scratch(),click,2);click.assert_called_once()
 def test_reward_ends_retries_even_if_ticket_reappears(self):
  controller=ScratchTicket();click=Mock()
  controller.update(scratch(),click,0)
  controller.update(report('daily_rewards_get'),click,1)
  controller.update(scratch(),click,4)
  click.assert_called_once()
 def test_full_wheel_flow_opens_ticket_then_closes_reward(self):
  c=Computer();near=report('menu','stage');near.frame['world_features']={'wheel_prompt':True,'hud_count':3}
  frames=iter([near]*4+[scratch(),report('daily_rewards_get')]+[near]*3)
  tree=DailyTasks(config(),lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  tree.gift('wheel')
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['e'])
  clicks=[a for a in c.actions if a.name=='click']
  self.assertEqual(len(clicks),2)
  self.assertEqual((clicks[0].arguments['x'],clicks[0].arguments['y']),(626,641))
 def test_startup_recognizes_existing_ticket_not_blank(self):
  r=scratch();r.frame['startup_template_only']=True
  d=StartupTree().decide(r)
  self.assertEqual(d['state'],'scratch_ticket');self.assertEqual(d['target']['label'],'scratch_open')
  self.assertEqual(d['post_input_grace'],2)
 def test_cancel_before_ticket_click(self):
  c=Computer();tree=DailyTasks(config(),lambda:scratch(),c,lambda _:None,should_yield=lambda:True)
  tree.active_gift='wheel'
  with self.assertRaises(RuntimeError):tree.until_free(click=True)
  self.assertFalse(c.actions)
 def test_false_ticket_without_anchor_is_not_clicked(self):
  r=scratch();r.frame['world_features']['anchors']={};click=Mock()
  ScratchTicket().update(r,click,0);click.assert_not_called()

if __name__=='__main__':unittest.main()
