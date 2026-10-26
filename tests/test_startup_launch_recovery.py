import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from modular_agent.agent.general import GeneralAgent
from modular_agent.agent.launcher import GameLauncher
from test_connected_agent import Computer, Model, Vision, GAME, PROFILE, screen

class StartupLaunchRecoveryTests(unittest.TestCase):
    def test_delayed_foreground_is_polled_before_failing(self):
        bg={**GAME,'foreground':False}
        computer=Computer()
        result=GameLauncher(Vision([[bg],[bg],[bg],[GAME]],screen()),computer,PROFILE).run('启动')
        self.assertTrue(result['verified'])
        self.assertTrue(any(a.name=='wait' for a in computer.actions))
        self.assertFalse(any(a.name=='launch' for a in computer.actions))

    def test_launch_skill_allowed_without_prior_screen(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams';folder.mkdir(parents=True)
            (folder/'launch.json').write_text(json.dumps(PROFILE))
            model=Model([{'decision':'use_skill','skill':'launch_game','domain':'hololive_dreams'}, {'decision':'done','reason':'主界面已出现'}])
            agent=GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=Vision([[]],screen()))
            with patch.object(agent,'_skill',return_value={'outcome':'success','verified':True}),patch.object(agent,'_observe',return_value=screen()):
                result=agent.execute('启动游戏')
            self.assertEqual(result['outcome'],'success')
            self.assertEqual(model.calls[1]['recent_results'][0]['outcome'],'success')

    def test_unconfirmed_foreground_does_not_start_clicking(self):
        bg={**GAME,'foreground':False}
        computer=Computer()
        result=GameLauncher(Vision([[bg]],screen()),computer,PROFILE).run('启动')
        self.assertEqual(result['outcome'],'failure')
        self.assertFalse(any(a.name=='click' for a in computer.actions))

    def test_transient_correct_size_is_not_accepted(self):
        sized={**GAME,'bounds':{'width':1280,'height':720}}
        reverted={**GAME,'bounds':{'width':1600,'height':900}}
        vision=Vision([[reverted],[sized],[sized],[reverted],[sized]],screen())
        computer=Computer()
        result=GameLauncher(vision,computer,{**PROFILE,'window_size':{'width':1280,'height':720}})._prepare_window(GAME,lambda x:None)
        self.assertEqual(result['bounds']['width'],1280)
        self.assertGreaterEqual(sum(a.name=='wait' for a in computer.actions),7)

    def test_small_startup_window_can_be_replaced_before_resize(self):
        small={**GAME,'bounds':{'width':584,'height':372}}
        main={**GAME,'handle':8,'class_name':'UnityWndClass','bounds':{'width':1280,'height':720}}
        computer=Computer()
        vision=Vision([[small],[main]],screen())
        result=GameLauncher(vision,computer,{**PROFILE,'window_size':{'width':1280,'height':720}})._prepare_window(small,lambda x:None)
        self.assertEqual(result['handle'],8)
        resizes=[a for a in computer.actions if a.name=='resize_window']
        self.assertEqual(resizes[0].arguments['handle'],8)
        self.assertEqual(computer.actions[0].name,'wait')
        self.assertEqual(computer.actions[0].arguments['duration'],2)

    def test_actual_unity_window_preferred_over_small_title_match(self):
        small={**GAME,'bounds':{'width':584,'height':372},'class_name':'Splash'}
        main={**GAME,'handle':8,'class_name':'UnityWndClass','bounds':{'width':1280,'height':720}}
        launcher=GameLauncher(Vision([[]],screen()),Computer(),PROFILE)
        self.assertEqual(launcher._window([small,main])['handle'],8)

    def test_steam_passes_configured_player_resolution_arguments(self):
        computer=Computer()
        args=['-screen-fullscreen','0','-screen-width','1280','-screen-height','720']
        config={**PROFILE,'launch_method':'steam','steam_executable':'D:/Steam/steam.exe','steam_app_id':'4282500','steam_launch_arguments':args}
        result=GameLauncher(Vision([[],[GAME],[GAME]],screen()),computer,config,clock=lambda:0).run('启动')
        self.assertTrue(result['verified'])
        launch=next(a for a in computer.actions if a.name=='launch')
        self.assertEqual(launch.arguments['arguments'],['-applaunch','4282500',*args])

    def test_drag_resize_uses_current_grip_with_alt(self):
        from modular_agent.core import SkillResult, Outcome
        class GripComputer(Computer):
            def perform(self,action):
                self.actions.append(action)
                data={'action':action.name}
                if action.name=='window_resize_info':
                    data.update(bounds={'x':100,'y':100,'width':584,'height':372},grip={'x':676,'y':464},work_area={'left':0,'top':0,'right':2560,'bottom':1600})
                return SkillResult(Outcome.SUCCESS,data,'ok')
        computer=GripComputer()
        launcher=GameLauncher(Vision([[GAME]],screen()),computer,PROFILE)
        launcher._drag_resize(GAME,{'width':1280,'height':720},lambda x:None)
        move=next(a for a in computer.actions if a.name=='move_to')
        drag=next(a for a in computer.actions if a.name=='drag')
        self.assertEqual(move.arguments,{'x':676,'y':464})
        self.assertEqual((drag.arguments['x'],drag.arguments['y']),(1372,812))
        self.assertEqual(drag.arguments['modifiers'],['alt'])
        self.assertFalse(any(a.name=='resize_window' for a in computer.actions))

    def test_drag_resize_does_not_drag_outside_work_area(self):
        from modular_agent.core import SkillResult, Outcome
        class GripComputer(Computer):
            def perform(self,action):
                self.actions.append(action)
                return SkillResult(Outcome.SUCCESS,{'bounds':{'x':2200,'y':100,'width':300,'height':300},'grip':{'x':2492,'y':392},'work_area':{'left':0,'top':0,'right':2560,'bottom':1600}},'ok')
        computer=GripComputer()
        launcher=GameLauncher(Vision([[GAME]],screen()),computer,PROFILE)
        with self.assertRaises(RuntimeError): launcher._drag_resize(GAME,{'width':1280,'height':720},lambda x:None)
        self.assertFalse(any(a.name=='drag' for a in computer.actions))

    def test_matching_size_skips_wait_and_resize(self):
        correct={**GAME,'bounds':{'x':100,'y':100,'width':1280,'height':764}}
        computer=Computer()
        launcher=GameLauncher(Vision([[correct]],screen()),computer,{**PROFILE,'window_size':{'width':1280,'height':764},'window_resize_method':'drag'})
        result=launcher._prepare_window(correct,lambda x:None)
        self.assertEqual(result['bounds']['height'],764)
        self.assertFalse(computer.actions)

    def test_close_enough_size_skips_drag(self):
        for width,height in ((1298,767),(1280,757)):
            correct={**GAME,'bounds':{'width':width,'height':height}}
            computer=Computer()
            launcher=GameLauncher(Vision([[correct]],screen()),computer,{**PROFILE,'window_size':{'width':1280,'height':764},'window_resize_method':'drag'})
            self.assertEqual(launcher._prepare_window(correct,lambda x:None)['bounds']['width'],width)
            self.assertFalse(computer.actions)
