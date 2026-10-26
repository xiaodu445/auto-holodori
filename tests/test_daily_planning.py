import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from modular_agent.domains.hololive_dreams.daily_plan import build_plan
from modular_agent.domains.hololive_dreams.daily_journal import RewardRecorder,DailyJournal
from modular_agent.local_models import execute_daily,run_daily_tasks
from modular_agent.agent.daily_tasks import DailyTasks,WORK
from test_daily_tasks import report,Computer

ROOT=Path(__file__).resolve().parents[1]
def config():
 return json.loads((ROOT/'domains/hololive_dreams/daily_tasks_config.json').read_text(encoding='utf-8'))

class DailyPlanningTests(unittest.TestCase):
 def test_selection_never_inherits_play(self):
  p=build_plan(config(),{'selected_tasks':['holowork','wheel']})
  self.assertEqual(p['tasks'],['holowork','wheel'])
 def test_entry_only_does_not_include_play(self):
  self.assertEqual(build_plan(config(),{'selected_tasks':['greed_cards_entry']})['tasks'],['greed_cards_entry'])
 def test_play_adds_visible_dependency(self):
  p=build_plan(config(),{'selected_tasks':['greed_cards_play']})
  self.assertEqual(p['tasks'],['greed_cards_entry','greed_cards_play'])
  self.assertEqual(p['added_dependencies'],['greed_cards_entry'])
 def test_invalid_requests(self):
  for r in ({'selected_tasks':['expiry_notice']},{'selected_tasks':['wheel','wheel']},
            {'record_rewards':'false'},{'max_rounds':True},{'selected_tasks':'wheel'},{'code':'run'}):
   with self.assertRaises(ValueError):build_plan(config(),r)
 def test_empty_plan_sends_no_input(self):
  computer=Computer();adapter=SimpleNamespace(root=ROOT,computer=computer)
  result=execute_daily(adapter,request={'selected_tasks':[]})
  self.assertTrue(result['verified']);self.assertFalse(computer.actions)
 def test_preview_never_constructs_computer(self):
  with patch('modular_agent.local_models.ActionComputer',side_effect=AssertionError('no desktop')):
   result=run_daily_tasks(ROOT,request={'selected_tasks':['wheel']},plan_only=True)
  self.assertFalse(result['executed'])
 def test_registered_extension_and_result_journal(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);dest=root/'domains/hololive_dreams';dest.mkdir(parents=True)
   shutil.copy2(ROOT/'domains/hololive_dreams/daily_tasks_config.json',dest/'daily_tasks_config.json')
   c=Computer();adapter=SimpleNamespace(root=root,computer=c,profiles=[{'domain':'hololive_dreams'}],
                                       _vision_for=lambda _:Mock())
   handler=Mock(return_value={'outcome':'success','verified':True})
   with patch('modular_agent.perception.template_import.import_game_templates',return_value={'errors':[]}):
    result=execute_daily(adapter,startup=False,request={'selected_tasks':['custom']},task_handlers={'custom':handler})
   handler.assert_called_once()
   self.assertEqual(result['items']['custom']['outcome'],'success')
   self.assertTrue((Path(result['trace_directory'])/'result.json').exists())
   self.assertTrue(c.released);self.assertFalse(c.actions)
 def test_builtin_cannot_be_overridden(self):
  with self.assertRaises(ValueError):build_plan(config(),{},['wheel'])

class DailyRewardTests(unittest.TestCase):
 def test_disabled_recording_does_not_call_reader(self):
  reader=Mock();rec=RewardRecorder(False,reader)
  rec.observe(report('daily_rewards_get'),True,'wheel')
  reader.assert_not_called();self.assertEqual(rec.records,[])
 def test_one_evidence_per_reward_episode(self):
  rec=RewardRecorder(True)
  rec.observe(report('daily_rewards_get'),True,'wheel')
  rec.observe(report('daily_rewards_get'),True,'wheel')
  self.assertEqual(len(rec.records),1)
  self.assertFalse(rec.records[0]['amounts_verified'])
  rec.observe(report(),False,'wheel')
  rec.observe(report('daily_rewards_get'),True,'wheel')
  self.assertEqual(len(rec.records),2)
 def test_reader_failure_does_not_abort_task(self):
  rec=RewardRecorder(True,Mock(side_effect=ValueError('unreadable')))
  rec.observe(report(),True,'holowork')
  self.assertIn('reader_error',rec.records[0])
 def test_callback_failure_is_reported(self):
  with tempfile.TemporaryDirectory() as root:
   journal=DailyJournal(root,Mock(side_effect=ValueError('callback')))
   journal('plan',tasks=[])
   self.assertEqual(journal.callback_errors,['callback'])

class DailySelectedExecutionTests(unittest.TestCase):
 def test_unselected_notice_never_dispatched(self):
  cfg=config();cfg['notification_scroll_pages']=1;c=Computer()
  free=report('menu','stage','attention')
  frames=iter([free]*4+[report('daily_notice_kaogan')]+[free]*3)
  tree=DailyTasks(cfg,lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds,selected_tasks=['holowork'])
  result=tree.notifications()
  self.assertEqual(set(result['items']),{'holowork'})
  self.assertEqual(result['items']['holowork']['outcome'],'skipped')
  self.assertEqual(sum(a.name=='click' for a in c.actions),2)
 def test_dialogue_overlay_not_free(self):
  r=report('menu','stage');r.frame['world_features']={'dialogue':True}
  c=Computer();tree=DailyTasks(config(),lambda:r,c,lambda _:None)
  self.assertFalse(tree.free(r))
 def test_shared_hud_without_legacy_icons_is_free(self):
  r=report();r.frame['world_features']={'hud_count':4}
  tree=DailyTasks(config(),lambda:r,Computer(),lambda _:None)
  self.assertTrue(tree.free(r))
 def test_claim_only_holowork_does_not_dispatch(self):
  cfg=config();c=Computer();free=report('menu','stage')
  frames=iter([report(n) for n in WORK[:4]]+[free]*3)
  tree=DailyTasks(cfg,lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds,redispatch_holowork=False)
  tree.holowork()
  self.assertTrue(any(a.name=='press' and a.arguments['key']=='escape' for a in c.actions))
  self.assertEqual(sum(a.name=='click' for a in c.actions),3)

 def test_wheel_prompt_can_remain_after_reward_closes(self):
  c=Computer();cfg=config();arrived=report('menu','stage','daily_wheel_interact')
  frames=iter([arrived]*4+[report('daily_rewards_get')]+[arrived]*3)
  tree=DailyTasks(cfg,lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  tree.gift('wheel')
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['e'])

 def test_unchanged_prompt_does_not_prove_interaction_finished(self):
  c=Computer();cfg=config();cfg['transition_timeout_seconds']=2
  arrived=report('menu','stage','daily_wheel_interact')
  tree=DailyTasks(cfg,lambda:arrived,c,lambda _:None,clock=lambda:c.seconds)
  with self.assertRaisesRegex(RuntimeError,'未确认回到自由界面'):
   tree.until_free(click=True,allow_interaction=True,require_transition=True)
  self.assertFalse(any(a.name in ('press','click') for a in c.actions))

 def test_unrecognized_notification_is_not_treated_as_empty(self):
  c=Computer();cfg=config();cfg['transition_timeout_seconds']=2
  free=report('menu','stage','attention')
  tree=DailyTasks(cfg,lambda:free,c,lambda _:None,clock=lambda:c.seconds,selected_tasks=['wheel'])
  result=tree.notifications()
  self.assertEqual(result['outcome'],'unknown')
  self.assertIn('不能证明',result['message'])
  self.assertEqual(sum(a.name=='click' for a in c.actions),1)

 def test_attention_can_use_window_relative_region(self):
  c=Computer();cfg=config();r=report('menu','stage')
  r.frame['bounds']['x']=400;r.frame['bounds']['y']=200
  tree=DailyTasks(cfg,lambda:r,c,lambda _:None)
  target=tree.attention_target(r)
  self.assertEqual(target['source'],'configured_region')
  self.assertEqual(target['bounds']['x']+12,400+round(1280*.205))
  self.assertEqual(target['bounds']['y']+12,200+round(764*.125))

 def test_attention_fallback_refuses_overlay_and_can_be_disabled(self):
  c=Computer();cfg=config();r=report('menu','stage','daily_rewards_get')
  tree=DailyTasks(cfg,lambda:r,c,lambda _:None)
  self.assertIsNone(tree.attention_target(r))
  cfg['attention_fixed_region']['enabled']=False
  self.assertIsNone(tree.attention_target(report('menu','stage')))

 def test_holowork_retries_reward_blank_before_waiting_setup(self):
  c=Computer();cfg=config();free=report('menu','stage')
  frames=iter([report(WORK[0]),report(WORK[1])]+[report('daily_rewards_get')]*9+
              [report(n) for n in WORK[3:]]+[free]*5)
  tree=DailyTasks(cfg,lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  tree.holowork()
  clicks=[a for a in c.actions if a.name=='click']
  blanks=[a for a in clicks if a.arguments['x']==1152 and a.arguments['y']==672]
  self.assertEqual(len(blanks),2)

 def test_generic_gift_prompt_stops_walk_without_legacy_template(self):
  c=Computer();cfg=config();near=report('menu','stage')
  near.frame['world_features']={'gift_prompt':True,'hud_count':3}
  free=report('menu','stage')
  frames=iter([near]*4+[report('daily_rewards_get')]+[free]*3)
  tree=DailyTasks(cfg,lambda:next(frames),c,lambda _:None,clock=lambda:c.seconds)
  tree.gift('the_cell')
  self.assertEqual([a.arguments['key'] for a in c.actions if a.name=='press'],['e'])
