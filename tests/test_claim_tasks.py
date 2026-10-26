import unittest
import tempfile
import shutil
from types import SimpleNamespace
from pathlib import Path
import cv2
import numpy as np
from unittest.mock import Mock,patch
from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks,annotate_enabled,TEMPLATES
from modular_agent.domains.hololive_dreams.daily_plan import build_plan
from modular_agent.perception.general import GeneralVision
from modular_agent.agent.daily_tasks import DailyTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config

ROOT=Path(__file__).resolve().parents[1]

class ClaimTests(unittest.TestCase):
 def setUp(self):
  self.c=Computer();self.r=report()
  self.d=DailyTasks(config(),lambda:self.r,self.c,lambda _:None,clock=lambda:self.c.seconds)
  self.d.report=self.r;self.flow=ClaimTasks(self.d)
 def test_modules_are_selectable_and_late(self):
  p=build_plan(config(),{'selected_tasks':['task_pass','events','achievements','wheel']})
  self.assertEqual(p['tasks'],['wheel','achievements','task_pass','events'])
 def test_default_unchanged(self):
  self.assertNotIn('events',build_plan(config())['tasks'])
 def test_claim_requires_enabled_and_region(self):
  r=report('claim_one');m=r.knowledge_matches[0]
  self.assertIsNone(self.flow.match(r,'one'))
  m['claim_enabled']=True
  self.assertIsNotNone(self.flow.match(r,'one'))
  self.assertIsNone(self.flow.match(r,'one',(.77,.26,.95,.82)))
 def test_scroll_never_clicks_objective(self):
  self.flow.scroll()
  self.assertEqual([a.name for a in self.c.actions],['move_to','scroll','wait'])
 def test_task_pt_before_pass_rewards(self):
  self.flow.page=Mock(return_value=self.r);self.flow.point=Mock();self.flow.scan=Mock()
  self.flow.task_pass()
  self.assertEqual(self.flow.point.call_args_list[-1].args,(.14,.265))
  self.assertEqual(self.flow.scan.call_count,4)
 def test_unknown_page_no_click(self):
  with self.assertRaisesRegex(RuntimeError,'未确认领取页面'):self.flow.page('event_page')
  self.assertFalse(any(a.name=='click' for a in self.c.actions))
 def test_reward_close_requires_confirmed_parent(self):
  frames=iter([report('daily_rewards_get')]+[report()]*100)
  self.d.observe=lambda:next(frames)
  with self.assertRaisesRegex(RuntimeError,'未确认完整奖励'):self.flow.claim(report('claim_one').knowledge_matches[0])
 def test_reward_success_returns_to_confirmed_page(self):
  frames=iter([report('daily_rewards_get'),report('claim_pass_page'),report('claim_pass_page')])
  self.d.observe=lambda:next(frames)
  self.flow.claim(report('claim_one').knowledge_matches[0])
  self.assertEqual(self.flow.claims,1)
 def test_unverified_scan_not_promoted_by_orchestrator(self):
  from modular_agent.local_models import execute_daily
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);dest=root/'domains/hololive_dreams';dest.mkdir(parents=True)
   shutil.copy2(ROOT/'domains/hololive_dreams/daily_tasks_config.json',dest/'daily_tasks_config.json')
   adapter=SimpleNamespace(root=root,computer=self.c,profiles=[{'domain':'hololive_dreams'}],_vision_for=lambda _:Mock())
   with patch('modular_agent.perception.template_import.import_game_templates',return_value={'errors':[]}),patch.object(ClaimTasks,'run',return_value={'outcome':'success','verified':False}) as run:
    result=execute_daily(adapter,lambda _:None,startup=False,request={'selected_tasks':['task_pass']})
   run.assert_called_once_with('task_pass')
   self.assertFalse(result['verified']);self.assertEqual(result['outcome'],'success')
 def test_colour_rejects_grey(self):
  m={'label':'claim_all','bounds':{'x':0,'y':0,'width':20,'height':20}}
  self.assertFalse(annotate_enabled([dict(m)],np.full((20,20,3),180,np.uint8),(0,0))[0]['claim_enabled'])
  img=np.zeros((20,20,3),np.uint8);img[:]=[245,180,30]
  self.assertFalse(annotate_enabled([dict(m)],img,(0,0))[0]['claim_enabled'])
  img[5:10,:]=255
  self.assertTrue(annotate_enabled([dict(m)],img,(0,0))[0]['claim_enabled'])
 def test_no_reward_does_not_repeat_click(self):
  self.d.report=report('claim_one');m=self.d.report.knowledge_matches[0]
  with self.assertRaisesRegex(RuntimeError,'未确认完整奖励'):self.flow.claim(m)
  self.assertEqual(sum(a.name=='click' for a in self.c.actions),1)
 def test_real_archived_positive_and_disabled(self):
  vision=GeneralVision.for_project(ROOT,'hololive_dreams',enable_ocr=False,enable_uia=False,enable_cv_buttons=False)
  try:
   for source,positive in [('0fa79e05-fa45-4357-9fbd-0aec03562164',True),('73fbf1d6-3348-4181-bbf4-d599c494280e',True),('049a80a7-aa25-44ca-bb15-81f4d487d435',False),('53418a90-0daa-44ae-bb50-0ae5aa489134',False),('6922dbdd-9ea0-41e3-8511-5456d63c4aef',False),('0d1d7ece-b2c2-4a82-ab2a-8980ea8f1849',False)]:
    path=ROOT/f'domains/hololive_dreams/data/world_reference/20261017/codex-clipboard-{source}.png'
    img=cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_COLOR)
    r=vision.analyze(img,environment='hololive_dreams',template_names=TEMPLATES,template_threshold=.92)
    self.assertEqual(bool(self.flow.match(r,'all',(.72,.80,.97,.96))),positive,source)
  finally:vision.close()

if __name__=='__main__':unittest.main()
