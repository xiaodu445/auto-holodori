import unittest
from modular_agent.agent.startup_tree import StartupTree, HUD
from modular_agent.perception.report import ScreenReport
from test_connected_agent import Computer, GAME

def frame(words):
    return ScreenReport(frame={'target_window_handle':7,'bounds':{'x':0,'y':0,'width':1400,'height':850}},windows=[GAME.copy()],texts=[{'id':'ocr:'+str(i),'text':w,'source':'ocr','bounds':{'x':300,'y':200+i*40,'width':80,'height':30}} for i,w in enumerate(words)])

class StartupTreeTests(unittest.TestCase):
    def test_hud_is_goal_but_not_when_reward_covers_it(self):
        tree=StartupTree()
        self.assertEqual(tree.decide(frame(HUD))['outcome'],'success')
        self.assertNotEqual(tree.decide(frame(list(HUD)+['每日奖励','继续'])).get('outcome'),'success')

    def test_reward_x_is_ignored_without_template_data(self):
        report=frame(['每日奖励','×','×'])
        report.texts[1]['bounds']['y']=10
        tree=StartupTree();d=tree.decide(report)
        self.assertEqual(d['action'],'center')
        self.assertNotIn('target',d)

    def test_rewards_continue_and_main_route(self):
        reports=iter([frame(['每日奖励','×']),frame(['继续']),frame(HUD)])
        computer=Computer();now=[0]
        def observe():
            now[0]+=7
            return next(reports)
        result=StartupTree().run(observe,computer,lambda x:None,clock=lambda:now[0])
        self.assertEqual(result['outcome'],'success')
        self.assertTrue(result['verified'])
        self.assertEqual(sum(a.name=='click' for a in computer.actions),2)
        self.assertGreater(computer.releases,0)

    def test_unknown_center_probe_is_bounded(self):
        computer=Computer();result=StartupTree(startup_grace=0,post_input_grace=0,max_center_attempts=2).run(lambda:frame(['未知启动内容']),computer,lambda x:None)
        self.assertEqual(result['outcome'],'unknown')
        self.assertEqual(sum(a.name=='click' for a in computer.actions),2)

    def test_loading_and_other_game_states_are_not_blind_clicks(self):
        tree=StartupTree()
        self.assertEqual(tree.decide(frame(['加载中']))['action'],'wait')
        for words in (['验证码'],['连接失败'],['High&Low','押注并开始游戏'],['MAP','电玩巨蛋城']):
            self.assertEqual(tree.decide(frame(words))['outcome'],'unknown')

    def test_guidance_and_stop_release_without_input(self):
        computer=Computer()
        result=StartupTree().run(lambda:frame(HUD),computer,lambda x:None,should_yield=lambda:True)
        self.assertEqual(result['outcome'],'unknown')
        self.assertFalse(computer.actions)
        computer.stopped=True
        self.assertEqual(StartupTree().run(lambda:frame(HUD),computer,lambda x:None)['outcome'],'failure')

    def test_game_must_be_focused_before_success(self):
        background=frame(HUD);background.windows[0]['foreground']=False
        frames=iter([background,frame(HUD)]);computer=Computer()
        result=StartupTree().run(lambda:next(frames),computer,lambda x:None)
        self.assertEqual(result['outcome'],'success')
        self.assertEqual(computer.actions[0].name,'focus')

    def test_top_launch_skill_waits_for_main_interface(self):
        import tempfile
        import json
        from pathlib import Path
        from unittest.mock import patch
        from modular_agent.agent.general import GeneralAgent
        from test_connected_agent import PROFILE, Model, Vision
        with tempfile.TemporaryDirectory() as root:
            domain=Path(root)/'domains'/'hololive_dreams'
            domain.mkdir(parents=True)
            (domain/'launch.json').write_text(json.dumps(PROFILE))
            agent=GeneralAgent(root,Computer(),Model([]),domain='hololive_dreams',vision=Vision([[GAME]],frame(HUD)))
            with patch('modular_agent.agent.general.GameLauncher.run',return_value={'outcome':'success','verified':True,'message':'window only'}),patch.object(agent,'_observe_startup',return_value=frame(HUD)) as observe:
                result=agent._skill({'skill':'launch_game','domain':'hololive_dreams'},'启动游戏',lambda x:None)
            self.assertEqual(result['verification'],'local_startup_ui_rule')
            self.assertIn('自由主界面',result['message'])
            observe.assert_called_once()

    def test_observed_loading_and_ocr_title_variants(self):
        tree=StartupTree()
        self.assertEqual(tree.decide(frame(['hololive-Dreams','Loading...']))['state'],'loading')
        self.assertEqual(tree.decide(frame(['APTO START','登录完成。']))['state'],'title_start')
        self.assertEqual(tree.decide(frame(['最小化','关闭','hololive-Dreams','×']))['action'],'center')

    def test_blank_loading_title_main_does_not_consume_probe_budget(self):
        tree=StartupTree();computer=Computer()
        reports=iter([frame(['hololive-Dreams']),frame(['Loading...']),frame(['APTO START']),frame(HUD)])
        result=tree.run(lambda:next(reports),computer,lambda x:None)
        self.assertEqual(result['outcome'],'success')
        self.assertEqual(sum(a.name=='click' for a in computer.actions),1)
        self.assertEqual(tree.center_attempts,1)

    def test_fast_unknown_observations_wait_before_asking(self):
        tree=StartupTree(startup_grace=6);computer=Computer()
        reports=iter([frame(['ver.1.2.1','Live2D']) for _ in range(6)]+[frame(HUD)])
        result=tree.run(lambda:next(reports),computer,lambda x:None,clock=lambda:0)
        self.assertEqual(result['outcome'],'success')
        self.assertFalse(any(a.name=='click' for a in computer.actions))

    def test_loading_deadline_uses_elapsed_time(self):
        tree=StartupTree(loading_timeout=10);computer=Computer();now=[0]
        def observe():
            now[0]+=6
            return frame(['Loading...'])
        result=tree.run(observe,computer,lambda x:None,clock=lambda:now[0])
        self.assertEqual(result['outcome'],'unknown')
        self.assertIn('超过',result['message'])
        self.assertFalse(any(a.name=='click' for a in computer.actions))

    def test_blinking_start_prompt_uses_current_game_center_with_cooldown(self):
        tree=StartupTree(startup_grace=0,post_input_grace=6);computer=Computer();now=[0]
        def observe():
            now[0]+=2
            if now[0]==2: return frame(['TAP TO START'])
            if now[0]<10: return frame(['hololive-Dreams'])
            return frame(HUD)
        result=tree.run(observe,computer,lambda x:None,clock=lambda:now[0])
        self.assertEqual(result['outcome'],'success')
        clicks=[a for a in computer.actions if a.name=='click']
        self.assertEqual(len(clicks),2)
        self.assertTrue(all(a.arguments['x']==1260 and a.arguments['y']==765 for a in clicks))

    def test_default_click_wait_is_point_three_and_stops_at_hud(self):
        computer=Computer();reports=iter([frame(['TAP TO START']),frame(HUD)])
        result=StartupTree().run(lambda:next(reports),computer,lambda x:None)
        self.assertEqual(result['outcome'],'success')
        clicks=[a for a in computer.actions if a.name=='click']
        self.assertEqual(len(clicks),1)
        self.assertEqual((clicks[0].arguments['x'],clicks[0].arguments['y']),(1260,765))
        self.assertEqual([a.arguments['duration'] for a in computer.actions if a.name=='wait'],[.3])

    def test_template_only_branch_ignores_ocr_and_requires_two_hud_frames(self):
        tree=StartupTree()
        report=frame(HUD)
        report.frame['startup_template_only']=True
        self.assertEqual(tree.decide(report)['action'],'center')
        report.knowledge_matches=[{'label':name,'similarity':.95} for name in ('menu','stage','task')]
        self.assertEqual(tree.decide(report)['state'],'confirm_hud')
        self.assertEqual(tree.decide(report)['outcome'],'success')
        report.knowledge_matches=[]
        self.assertEqual(tree.decide(report)['action'],'center')

    def test_hud_confirmation_tolerates_minor_score_flicker_without_clicking(self):
        tree=StartupTree()
        first=frame([]);first.frame['startup_template_only']=True
        first.knowledge_matches=[{'label':n,'similarity':v} for n,v in zip(('menu','stage','task'),(.995,.906,.905))]
        self.assertEqual(tree.decide(first)['state'],'confirm_hud')
        second=frame([]);second.frame['startup_template_only']=True
        second.knowledge_matches=[{'label':n,'similarity':v} for n,v in zip(('menu','stage','task'),(.996,.905,.891))]
        self.assertEqual(tree.decide(second)['outcome'],'success')

    def test_low_scores_cannot_initiate_hud_confirmation(self):
        tree=StartupTree();report=frame([]);report.frame['startup_template_only']=True
        report.knowledge_matches=[{'label':n,'similarity':.84} for n in ('menu','stage','task')]
        self.assertEqual(tree.decide(report)['state'],'startup_probe')

    def test_two_strong_icons_stop_without_clicking_weak_task(self):
        tree=StartupTree();computer=Computer()
        report=frame([]);report.frame['startup_template_only']=True
        report.knowledge_matches=[{'label':n,'similarity':v} for n,v in zip(('menu','stage','task'),(1.,.97,.775))]
        result=tree.run(lambda:report,computer,lambda x:None)
        self.assertEqual(result['outcome'],'success')
        self.assertFalse(any(a.name=='click' for a in computer.actions))

    def test_one_strong_icon_and_duplicate_matches_cannot_confirm(self):
        tree=StartupTree();report=frame([]);report.frame['startup_template_only']=True
        report.knowledge_matches=[{'label':'menu','similarity':1.}]*3
        self.assertEqual(tree.decide(report)['state'],'startup_probe')

    def test_focus_recovery_allows_startup_window_to_stabilize(self):
        tree=StartupTree(startup_grace=2);computer=Computer();state=[0]
        def observe():
            state[0]+=1
            r=frame([]);r.frame['startup_template_only']=True
            r.windows[0]['foreground']=state[0]>=3
            if state[0]>=3:r.knowledge_matches=[{'label':'menu','similarity':.95},{'label':'stage','similarity':.95}]
            return r
        result=tree.run(observe,computer,lambda x:None)
        self.assertEqual(result['outcome'],'success')
