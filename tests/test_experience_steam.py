import json
from pathlib import Path
import tempfile
import unittest
from modular_agent.agent.general import GeneralAgent
from modular_agent.agent.launcher import GameLauncher
from modular_agent.agent.progress_evidence import fingerprint
from modular_agent.memory.agent_knowledge import AgentKnowledge
from test_connected_agent import Computer, Model, Vision, GAME, PROFILE, screen
from modular_agent.perception.report import ScreenReport

class ExperienceSteamTests(unittest.TestCase):
    def test_steam_launch_never_clicks_desktop_icon(self):
        computer=Computer()
        config={**PROFILE,'launch_method':'steam','steam_executable':'D:/Steam/steam.exe','steam_app_id':'4282500'}
        result=GameLauncher(Vision([[],[GAME],[GAME]],screen()),computer,config,clock=lambda:0).run('进入游戏')
        self.assertTrue(result['verified'])
        actions=[a for a in computer.actions if a.name=='launch']
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0].arguments,{'executable':'D:/Steam/steam.exe','arguments':['-applaunch','4282500']})
        self.assertFalse(any(a.name in ('show_desktop','click') for a in computer.actions))

    def test_invalid_steam_configuration_does_not_fall_back_to_icon(self):
        computer=Computer()
        config={**PROFILE,'launch_method':'steam','steam_executable':'game.exe','steam_app_id':'4282500'}
        result=GameLauncher(Vision([[]],screen()),computer,config).run('进入游戏')
        self.assertEqual(result['outcome'],'failure')
        self.assertFalse(computer.actions)

    def test_retry_feedback_is_automatically_recorded_and_loaded_next_task(self):
        with tempfile.TemporaryDirectory() as root:
            before=ScreenReport(frame={'visual_signature':'before'})
            after=ScreenReport(frame={'visual_signature':'after'})
            class ChangingVision(Vision):
                def __init__(self): super().__init__([[]],before); self.frames=iter([before,before,after])
                def observe(self,**kwargs): return next(self.frames)
            action={'decision':'act','actions':[{'name':'click','arguments':{'x':100,'y':80}}]}
            model=Model([{'decision':'observe'},action,action,{'decision':'done','reason':'已出现界面变化'}])
            computer=Computer();agent=GeneralAgent(root,computer,model,vision=ChangingVision())
            self.assertEqual(agent.execute('进入游戏')['outcome'],'success')
            self.assertEqual(model.calls[2]['progress_evidence']['same_action_no_change_count'],1)
            self.assertTrue(model.calls[3]['progress_evidence']['retry_followed_by_change'])
            notes=list((Path(root)/'knowledge'/'global'/'agent_notes').glob('*.md'))
            self.assertEqual(len(notes),1)
            self.assertIn('未经独立规则验证',notes[0].read_text(encoding='utf-8'))
            self.assertTrue(model.calls[3]['relevant_knowledge'])
            next_model=Model([{'decision':'escalate','reason':'检查知识上下文'}])
            agent.model=next_model
            agent.execute('进入游戏')
            self.assertTrue(next_model.calls[0]['relevant_knowledge'])

    def test_note_deduplication(self):
        with tempfile.TemporaryDirectory() as root:
            knowledge=AgentKnowledge(root)
            first=knowledge.write('状态相同可重试','观察到重试后变化')
            second=knowledge.write('状态相同可重试','观察到重试后变化')
            self.assertEqual(first['path'],second['path'])
            self.assertTrue(second['deduplicated'])

    def test_default_loop_goes_beyond_old_limits(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'observe'}]+[{'decision':'read_knowledge','query':'经验'}]*130+[{'decision':'done','reason':'任务完成'}])
            result=GeneralAgent(root,Computer(),model,vision=Vision([[]],screen())).execute('运行长任务')
            self.assertEqual(result['outcome'],'success')
            self.assertEqual(len(model.calls),132)
            self.assertLessEqual(len(model.calls[-1]['recent_results']),5)

    def test_unlimited_loop_can_still_stop(self):
        with tempfile.TemporaryDirectory() as root:
            computer=Computer();computer.stopped=False
            class StopModel(Model):
                def complete(self,instructions,payload):
                    response=super().complete(instructions,payload)
                    if len(self.calls)==15: computer.stopped=True
                    return response
            model=StopModel([{'decision':'observe'}]+[{'decision':'act','actions':[{'name':'wait','arguments':{'duration':0}}]}]*19)
            result=GeneralAgent(root,computer,model,vision=Vision([[]],screen())).execute('长任务')
            self.assertEqual(result['outcome'],'failure')
            self.assertIn('停止',result['message'])
            self.assertEqual(len(model.calls),15)

    def test_repeated_same_observation_requests_end_with_explanation(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'observe','detail':'full'}]*10)
            result=GeneralAgent(root,Computer(),model,vision=Vision([[]],screen())).execute('查找入口')
            self.assertEqual(result['outcome'],'unknown')
            self.assertIn('连续重复观察',result['message'])
            self.assertEqual(len(model.calls),4)
            self.assertIn('next_step_requirement',model.calls[2]['recent_results'][-1])
            records=list((Path(root)/'runtime'/'memory'/'task_sessions').glob('*.md'))
            self.assertIn('连续重复观察',records[0].read_text(encoding='utf-8'))

    def test_volatile_detection_ids_do_not_mean_progress(self):
        first=ScreenReport(frame={},knowledge_matches=[{'id':'a','label':'play','bounds':{'x':50,'y':50,'width':100,'height':40},'similarity':.99}])
        second=ScreenReport(frame={},knowledge_matches=[{'id':'b','label':'play','bounds':{'x':50,'y':50,'width':100,'height':40},'similarity':.98}])
        self.assertEqual(fingerprint(first),fingerprint(second))
