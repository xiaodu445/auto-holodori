import unittest
from unittest.mock import Mock
import numpy as np
from modular_agent.domains.hololive_dreams.interaction import (
 InteractionPolicy,RetryBudget,policy_for,SCENARIOS,transition,text_button)
from modular_agent.domains.hololive_dreams.popup_recovery import annotate
from modular_agent.agent.startup_tree import StartupTree
from test_daily_tasks import report

class ProtocolTests(unittest.TestCase):
 def setUp(self):self.now=0.;self.sent=[]
 def wait(self,s):self.now+=s
 def run_flow(self,observe,**kw):
  args=dict(observe=observe,send=lambda t:self.sent.append(t),resolve=lambda r:r.knowledge_matches[0] if r.knowledge_matches else None,
   source=lambda r:any(m['label']=='source' for m in r.knowledge_matches),
   completed=lambda r:any(m['label']=='done' for m in r.knowledge_matches),wait=self.wait,clock=lambda:self.now,
   policy=InteractionPolicy(timeout=5,retry_interval=1,poll_interval=.25))
  args.update(kw);return transition(**args)
 def test_first_input_dropped_retries_until_confirmed(self):
  r=self.run_flow(lambda:report('source') if len(self.sent)<2 else report('done'))
  self.assertEqual(len(self.sent),2);self.assertEqual(r.knowledge_matches[0]['label'],'done')
 def test_destination_already_present_sends_nothing(self):
  self.run_flow(lambda:report('done'));self.assertEqual(self.sent,[])
 def test_no_destination_never_claims_success(self):
  with self.assertRaisesRegex(RuntimeError,'未确认'):self.run_flow(lambda:report('source'))
  self.assertEqual(len(self.sent),3)
 def test_disabled_does_not_send(self):
  r=report('source');r.knowledge_matches[0]['enabled']=False
  with self.assertRaises(RuntimeError):self.run_flow(lambda:r)
  self.assertEqual(self.sent,[])
 def test_unknown_no_target_does_not_blind_click(self):
  with self.assertRaises(RuntimeError):self.run_flow(lambda:report())
  self.assertEqual(self.sent,[])
 def test_loading_does_not_click_even_with_background_target(self):
  r=report('source');r.texts=[{'text':'loading'}]
  with self.assertRaises(RuntimeError):self.run_flow(lambda:r)
  self.assertEqual(self.sent,[])
 def test_focus_loss_aborts(self):
  r=report('source');r.windows[0]['foreground']=False
  with self.assertRaisesRegex(RuntimeError,'失焦'):self.run_flow(lambda:r)
  self.assertEqual(self.sent,[])
 def test_stop_after_capture_prevents_input(self):
  checks=[0]
  def check():
   checks[0]+=1
   if checks[0]==2:raise RuntimeError('stop')
  with self.assertRaisesRegex(RuntimeError,'stop'):self.run_flow(lambda:report('source'),check=check)
  self.assertEqual(self.sent,[])
 def test_discovery_once_and_never_confuses_it_with_completion(self):
  discovery=Mock(return_value=report());recover=Mock(return_value=False)
  with self.assertRaises(RuntimeError):self.run_flow(lambda:report(),discover=discovery,recover=recover)
  discovery.assert_called_once();recover.assert_called_once()
 def test_reward_preempts_destination_visible_behind(self):
  r=report('done','daily_rewards_get');n=[0]
  def recover(r):n[0]+=1
  self.run_flow(lambda:r if not n[0] else report('done'),recover=recover)
  self.assertEqual(n[0],1);self.assertEqual(self.sent,[])
 def test_no_retry_original_action_after_reward(self):
  def observe():
   if not self.sent:return report('source')
   if self.now<1:return report('daily_rewards_get')
   return report('source')
  with self.assertRaises(RuntimeError):self.run_flow(observe,recover=lambda r:True)
  self.assertEqual(len(self.sent),1)
 def test_passive_and_realtime_never_repeat_inputs(self):
  for name in ('live_matching','loading','rhythm_play'):
   self.assertFalse(RetryBudget(policy_for(name)).ready(100))
 def test_nonrepeatable_spending_action_has_one_send(self):
  b=RetryBudget(policy_for('bet_or_spend'));self.assertTrue(b.ready(0));b.sent(0)
  self.assertFalse(b.ready(100))
 def test_scene_must_be_registered(self):
  with self.assertRaises(ValueError):policy_for('new_unreviewed_scene')
  self.assertIn('dialogue',SCENARIOS);self.assertIn('holowork',SCENARIOS)
 def test_invalid_policy_rejected(self):
  for kw in ({'timeout':float('nan')},{'max_attempts':0},{'mode':'blind_repeat'},{'poll_interval':0}):
   with self.assertRaises(ValueError):InteractionPolicy(**kw)

class TextPopupTests(unittest.TestCase):
 def popup(self,title='获得奖励',label='确定',white=True):
  r=report();q=dict(x=0,y=0,width=20,height=20)
  r.texts=[{'text':title},{'text':label,'confidence':.99,'button_ids':['b'],'bounds':q}]
  r.buttons=[{'id':'b','bounds':q,'enabled':None,'label':'','confidence':.35,'semantic_confirmed':False}]
  image=np.zeros((20,20,3),np.uint8);image[:]=[245,180,30]
  if white:image[5:10,:]=255
  annotate(r,image,(0,0));return r
 def test_registered_popup_gets_enabled_text_target(self):
  r=self.popup();t=text_button(r,('确定',),known_page=bool(r.frame.get('confirmed_popup')))
  self.assertIsNotNone(t);self.assertEqual(t['label'],'确定')
 def test_raw_ocr_not_clickable(self):
  r=report();r.texts=[{'text':'确定','confidence':1}]
  self.assertIsNone(text_button(r,('确定',),known_page=True))
 def test_grey_or_unknown_popup_does_not_enable_button(self):
  for r in (self.popup(white=False),self.popup(title='未知窗口')):
   self.assertIsNone(text_button(r,('确定',),known_page=bool(r.frame.get('confirmed_popup'))))
 def test_purchase_or_match_confirmation_never_auto_clicked(self):
  for title,label in [('确认购买','确定'),('获得奖励','决定成员'),('兑换奖励','确定')]:
   r=self.popup(title,label)
   self.assertIsNone(text_button(r,(label,),known_page=bool(r.frame.get('confirmed_popup'))))
 def test_startup_uses_popup_button_instead_of_blank(self):
  r=self.popup();r.frame['startup_template_only']=True
  d=StartupTree().decide(r)
  self.assertEqual(d['action'],'click');self.assertEqual(d['target']['label'],'确定')
 def test_ocr_close_glyph_cannot_target_window_chrome(self):
  r=self.popup(label='×')
  self.assertIsNone(text_button(r,('关闭',),known_page=bool(r.frame.get('confirmed_popup'))))
 def test_daily_ocr_only_enabled_for_explicit_recovery(self):
  from modular_agent.local_models import observe_daily
  from test_daily_tasks import Computer
  from unittest.mock import patch
  v=Mock();v.knowledge.last_diagnostics=[];v.observe.return_value=report()
  with patch('modular_agent.local_models.GameLauncher') as launcher:
   launcher.return_value._window.return_value={'handle':7,'foreground':True}
   observe_daily(v,Computer(),{},lambda _:None,recovery=True)
  self.assertTrue(v.observe.call_args.kwargs['enable_ocr'])
  self.assertTrue(v.observe.call_args.kwargs['enable_cv_buttons'])

if __name__=='__main__':unittest.main()
