import json
import unittest
from pathlib import Path
from modular_agent.agent.daily_tasks import DailyTasks,WORK,validate_config
from modular_agent.perception.report import ScreenReport
from modular_agent.core import Outcome
from types import SimpleNamespace


def report(*labels):
    return ScreenReport(frame={'target_window_handle':7,'bounds':{'x':0,'y':0,'width':1280,'height':764}},
        windows=[{'handle':7,'foreground':True}],knowledge_matches=[{'label':n,'similarity':.95,'threshold':.85,
        'bounds':{'x':1100 if n=='daily_back' else 100,'y':100,'width':80,'height':30}} for n in labels])

class Computer:
    live=True;stopped=False
    def __init__(self): self.actions=[];self.seconds=0;self.released=False
    def perform(self,a):
        self.actions.append(a);self.seconds+=a.arguments.get('duration',0)
        return SimpleNamespace(outcome=Outcome.SUCCESS,message='')
    def release_all(self): self.released=True

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads(Path('domains/hololive_dreams/models/daily_tasks_config.json').read_text(encoding='utf-8'))
        self.c=Computer()
    def tree(self,frames):
        sequence=iter(frames)
        return DailyTasks(self.config,lambda:next(sequence),self.c,lambda s:None,clock=lambda:self.c.seconds)
    def test_holowork_sequence_and_back(self):
        frames=[report(n) for n in WORK]+[report('menu','stage')]*5
        tree=self.tree(frames);tree.holowork()
        self.assertEqual(len([a for a in self.c.actions if a.name=='click']),7)
    def test_successor_page_skips_missing_previous_step(self):
        frames=[report(n) for n in WORK[3:]]+[report('menu','stage')]*5
        self.tree(frames).holowork()
        self.assertEqual(len([a for a in self.c.actions if a.name=='click']),4)
    def test_duplicate_button_is_bounded(self):
        t=DailyTasks(self.config,lambda:report(WORK[0]),self.c,lambda s:None,clock=lambda:self.c.seconds)
        with self.assertRaisesRegex(RuntimeError,'重复三次'):t.holowork()
        self.assertEqual(len([a for a in self.c.actions if a.name=='click']),3)
    def test_reward_and_notification_override_visible_hud(self):
        t=self.tree([])
        self.assertTrue(t.free(report('menu','stage')))
        self.assertFalse(t.free(report('menu','stage','daily_rewards_get')))
        self.assertFalse(t.free(report('menu','stage','daily_notice_holowork')))
        self.assertFalse(t.free(report('menu','stage','daily_gift_interact')))
        self.assertTrue(t.free(report('menu','stage','daily_gift_interact'),True))
    def test_holo_home_configurable_route_and_gift_click(self):
        self.config['holo_home_route']=[{'key':k,'seconds':3} for k in ('w','d','w')]
        free=report('menu','stage')
        frames=[free]*6+[report('menu','stage','daily_gift_interact'),report('daily_rewards_get')]+[free]*3
        self.tree(frames).gift('holo_home')
        holds=[a.arguments for a in self.c.actions if a.name=='press']
        self.assertEqual(holds,[{'key':k,'duration':3} for k in ('w','d','w')])
        self.assertTrue(all(a.arguments.get('modifiers')==['alt'] for a in self.c.actions if a.name=='click'))
    def test_wheel_uses_e_once(self):
        arrived=report('menu','stage','daily_wheel_interact');free=report('menu','stage')
        self.tree([arrived]*4+[report('daily_rewards_get')]+[free]*3).gift('wheel')
        self.assertEqual([a.arguments['key'] for a in self.c.actions if a.name=='press'],['e'])
    def test_focus_loss_rejects_input(self):
        r=report('menu','stage');r.windows[0]['foreground']=False
        result=self.tree([r]).notifications()
        self.assertEqual(result['outcome'],'unknown');self.assertTrue(self.c.released)
        self.assertFalse(self.c.actions)
    def test_human_guidance_releases_without_input(self):
        t=self.tree([]);t.should_yield=lambda:True
        result=t.notifications()
        self.assertEqual(result['outcome'],'unknown');self.assertTrue(self.c.released)
        self.assertFalse(self.c.actions)
    def test_unknown_notification_skipped(self):
        free=report('menu','stage','attention')
        empty=report('attention');empty.frame['world_features']={'notification_panel':True,'notification_rows':0}
        t=self.tree([free]*4+[empty]*9+[free]*3)
        result=t.notifications()
        self.assertEqual(result['outcome'],'success')
        self.assertTrue(all(item['outcome']=='skipped' and not item['verified'] for item in result['items'].values()))
    def test_invalid_route_rejected(self):
        self.config['holo_home_route'][0]['seconds']=100
        with self.assertRaises(ValueError):validate_config(self.config)

    def test_back_is_not_clicked_before_decide_was_dispatched(self):
        r=report('daily_back')
        t=DailyTasks(self.config,lambda:r,self.c,lambda s:None,clock=lambda:self.c.seconds)
        with self.assertRaisesRegex(RuntimeError,'等待超时'):t.holowork()
        self.assertFalse(any(a.name=='click' for a in self.c.actions))

    def test_summary_false_match_does_not_override_member_setup(self):
        frames=[report('daily_work_recommend','daily_work_claim_summary'),report('daily_work_decide'),
                report('daily_back')]+[report('menu','stage')]*5
        self.tree(frames).holowork()
        self.assertEqual(len([a for a in self.c.actions if a.name=='click']),3)

    def test_daily_observer_restores_focus_before_capture(self):
        from unittest.mock import patch,Mock
        from modular_agent.local_models import observe_daily
        game={'handle':7,'foreground':False};focused={'handle':7,'foreground':True}
        vision=Mock();vision.knowledge.last_diagnostics=[];vision.observe.return_value=report()
        with patch('modular_agent.local_models.GameLauncher') as cls:
            cls.return_value._window.return_value=game
            cls.return_value._focus_verified.return_value=focused
            observe_daily(vision,self.c,{},lambda s:None)
            cls.return_value._focus_verified.assert_called_once_with(game)
            self.assertEqual(vision.observe.call_args.kwargs['window_handle'],7)
            self.assertFalse(vision.observe.call_args.kwargs['enable_ocr'])
            self.assertEqual(vision.observe.call_args.kwargs['template_threshold'],.6)

    def test_daily_observer_does_not_refocus_on_guidance(self):
        from unittest.mock import patch,Mock
        from modular_agent.local_models import observe_daily
        with patch('modular_agent.local_models.GameLauncher') as cls:
            with self.assertRaises(RuntimeError):observe_daily(Mock(),self.c,{},lambda s:None,lambda:True)
            cls.assert_not_called()

    def test_daily_threshold_point_six_overrides_registry(self):
        self.config['template_threshold']=.6
        t=self.tree([]);r=report('daily_gift_interact')
        r.knowledge_matches[0]['similarity']=.61
        self.assertIsNotNone(t.target('daily_gift_interact',r))
        r.knowledge_matches[0]['similarity']=.59
        self.assertIsNone(t.target('daily_gift_interact',r))

    def test_back_false_matches_do_not_block_free_scene(self):
        t=self.tree([]);r=report('menu','stage','task','daily_back')
        r.knowledge_matches[-1]['bounds']={'x':100,'y':680,'width':50,'height':50}
        self.assertTrue(t.free(r))
        self.assertIsNone(t.target('daily_back',r))

    def test_back_arrow_only_accepted_at_upper_right(self):
        t=self.tree([]);r=report('daily_back')
        self.assertIsNotNone(t.target('daily_back',r))
