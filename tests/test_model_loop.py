import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_connected_agent import Computer, Vision, Model, screen, icon, PROFILE
from modular_agent.agent.general import GeneralAgent
from modular_agent.memory.agent_knowledge import AgentKnowledge

class CountingVision(Vision):
    def __init__(self): super().__init__([[]],screen([icon()])); self.observations=0
    def observe(self,**kwargs): self.observations+=1; return self.report

class ModelLoopTests(unittest.TestCase):
    def test_model_requests_first_observation_then_actions_feedback(self):
        with tempfile.TemporaryDirectory() as root:
            vision=CountingVision(); c=Computer()
            model=Model([{'decision':'observe'},
                {'decision':'act','actions':[{'name':'click_target','arguments':{'id':'i'}}],'delay_seconds':1.5},
                {'decision':'done','reason':'窗口已出现'}])
            result=GeneralAgent(root,c,model,vision=vision).execute('启动hololivedreams')
            self.assertEqual(vision.observations,2)
            self.assertIsNone(model.calls[0]['screen'])
            self.assertIsNotNone(model.calls[1]['screen'])
            self.assertEqual(model.calls[2]['recent_results'][-1]['decision'],'act')
            self.assertIn(1.5,[a.arguments['duration'] for a in c.actions if a.name=='wait'])
            self.assertEqual(result['outcome'],'success')
    def test_model_knowledge_read_write_and_provenance(self):
        with tempfile.TemporaryDirectory() as root:
            vision=CountingVision(); c=Computer()
            path=Path(root)/'knowledge'; path.mkdir()
            (path/'launch.md').write_text('# 启动经验\n\n启动需要双击。',encoding='utf-8')
            model=Model([{'decision':'observe'},
                {'decision':'read_knowledge','query':'启动'},
                {'decision':'write_knowledge','summary':'启动后应检查窗口','evidence':'本地窗口列表显示窗口已出现'},
                {'decision':'done','reason':'已检查窗口'}])
            GeneralAgent(root,c,model,vision=vision).execute('启动')
            self.assertTrue(model.calls[2]['recent_results'][-1]['entries'])
            notes=list((Path(root)/'knowledge'/'global'/'agent_notes').glob('*.md'))
            self.assertEqual(len(notes),1)
            self.assertIn('未经独立规则验证',notes[0].read_text(encoding='utf-8'))
            self.assertEqual(model.calls[3]['recent_results'][-1]['verification'],'model_reported')
    def test_no_operation_before_observation(self):
        with tempfile.TemporaryDirectory() as root:
            c=Computer(); model=Model([{'decision':'act','actions':[{'name':'press','arguments':{'key':'w'}}]}, {'decision':'escalate'}])
            result=GeneralAgent(root,c,model,vision=CountingVision()).execute('移动')
            self.assertFalse(c.actions)
            self.assertEqual(model.calls[1]['recent_results'][-1]['outcome'],'failure')
    def test_unobserved_done_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            result=GeneralAgent(root,Computer(),Model([{'decision':'done','reason':'完成'}]),vision=CountingVision()).execute('启动')
            self.assertEqual(result['outcome'],'failure')
    def test_skill_called_only_after_model_choice_then_feedback(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'domains'/'hololive_dreams'; path.mkdir(parents=True)
            (path/'launch.json').write_text(json.dumps(PROFILE),encoding='utf-8')
            model=Model([{'decision':'observe'},
                {'decision':'use_skill','skill':'launch_game','domain':'hololive_dreams'},
                {'decision':'done','reason':'启动结果和窗口信息都已确认'}])
            vision=CountingVision(); agent=GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=vision)
            with patch('modular_agent.agent.general.GameLauncher.run',return_value={'outcome':'success','verified':True,'message':'window found'}) as launch:
                agent.execute('启动hololivedreams')
            launch.assert_called_once()
            self.assertEqual(vision.observations,3)  # Extra startup-tree initial-state observation.
            self.assertEqual(model.calls[2]['recent_results'][-1]['decision'],'use_skill')
    def test_model_call_failure_does_not_operate(self):
        with tempfile.TemporaryDirectory() as root:
            c=Computer()
            result=GeneralAgent(root,c,Model([]),vision=CountingVision()).execute('启动')
            self.assertEqual(result['outcome'],'failure'); self.assertFalse(c.actions)
    def test_note_cannot_choose_arbitrary_output_path(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError): AgentKnowledge(root,'../../outside')

if __name__=='__main__': unittest.main()
