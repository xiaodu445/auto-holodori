import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.perception.general import GeneralVision
from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks,templates_for,annotate_enabled
from modular_agent.agent.daily_tasks import DailyTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config
ROOT=Path(__file__).resolve().parents[1]

class ClaimVariantTests(unittest.TestCase):
 def setUp(self):
  self.c=Computer();self.r=report()
  self.d=DailyTasks(config(),lambda:self.r,self.c,lambda _:None,clock=lambda:self.c.seconds)
  self.d.report=self.r;self.f=ClaimTasks(self.d)
 def test_evidence_and_badge_independent_of_task_text(self):
  v=GeneralVision.for_project(ROOT,'hololive_dreams',enable_ocr=False,enable_uia=False,enable_cv_buttons=False)
  try:
   for source,task,anchor in [('3723fc7c-8137-4491-8a6d-5d7ff1af09f0','events','event_home'),('32e0fbcd-b280-4903-9a77-9bda1f7f5d03','events','event_carousel'),('5162868c-17a2-494f-83d6-d25fd58fe187','task_pass','pass_page')]:
    p=ROOT/f'domains/hololive_dreams/data/world_reference/20261025/codex-clipboard-{source}.png'
    image=cv2.imdecode(np.fromfile(str(p),np.uint8),1)
    def analyze(img):return v.analyze(img,environment='hololive_dreams',template_names=templates_for(task),template_threshold=.92)
    r=analyze(image);self.assertIsNotNone(self.f.match(r,anchor));self.assertIsNotNone(self.f.match(r,'close'))
    if task=='task_pass':self.assertIsNone(self.f.match(r,'all'))
    if anchor=='event_home':
     self.assertFalse(self.f.match(r,anchor)['notification_badge'])
     cv2.circle(image,(1220,421),10,(180,60,245),-1)
     self.assertTrue(self.f.match(analyze(image),anchor)['notification_badge'])
  finally:v.close()
 def test_disabled_button_never_claims_or_scrolls(self):
  self.f.page=Mock(return_value=report('claim_all_task'))
  self.f.claim=Mock();self.f.scroll=Mock()
  self.f.scan(('pass_page',),pages=1)
  self.f.claim.assert_not_called();self.f.scroll.assert_not_called()
 def test_limit_text_does_not_override_enabled_button(self):
  r=report('claim_pt_limit','claim_all_task');m=r.knowledge_matches[1]
  m['claim_enabled']=True;m['bounds'].update(x=1050,y=670)
  self.f.page=Mock(side_effect=[r,report()]);self.f.claim=Mock()
  self.f.scan(('pass_page',),pages=1)
  self.f.claim.assert_called_once()
 def test_repeat_card_stops_before_second_entry(self):
  r=report('claim_event_carousel','claim_event_go');r.knowledge_matches[1]['bounds'].update(x=1100,y=670)
  r.frame['claim_search']={'event_card':[80]*288}
  self.f.page=Mock(return_value=r);self.f.navigate=Mock(return_value=report('claim_event_page'))
  self.f.scan=Mock();self.f.scroll=Mock();self.r=r
  self.f.events();self.assertEqual(self.f.navigate.call_count,1)
 def test_failed_module_leaves_but_not_completed(self):
  self.d.until_free=Mock();self.f.navigate=Mock();self.f.task_pass=Mock(side_effect=RuntimeError('unknown event'))
  self.f.leave=Mock()
  result=self.f.run('task_pass')
  self.f.leave.assert_called_once();self.assertEqual(result['outcome'],'unknown');self.assertTrue(result['returned_to_world'])
 def test_stop_does_not_send_cleanup_input(self):
  self.c.stopped=True
  with self.assertRaises(RuntimeError):self.f.run('events')
  self.assertEqual(self.c.actions,[])
 def test_white_checkmark_does_not_enable_grey_text(self):
  img=np.full((30,120,3),(245,180,30),np.uint8);img[:,:30]=255
  m={'label':'claim_all_task','bounds':dict(x=0,y=0,width=120,height=30)}
  self.assertFalse(annotate_enabled([m],img,(0,0))[0]['claim_enabled'])
 def test_exit_retries_dropped_close_with_spacing(self):
  close=report('claim_close');close.knowledge_matches[0]['bounds'].update(x=1200,y=80)
  sent=[]
  original=self.d.click
  def click(target):sent.append(self.c.seconds);original(target)
  self.d.click=click
  def capture():
   self.d.report=close if len(sent)<2 else report('menu','stage')
   return self.d.report
  self.d.capture=capture
  self.f.leave()
  self.assertEqual(len(sent),2);self.assertGreaterEqual(sent[1]-sent[0],2)
