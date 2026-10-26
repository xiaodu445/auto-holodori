import json
import tempfile
import unittest
from pathlib import Path
from modular_agent.agent.general import GeneralAgent
from test_connected_agent import Computer, Model, Vision, PROFILE, screen

class CurrentWindowContractTests(unittest.TestCase):
    def agent(self,root,model):
        folder=Path(root)/'domains'/'hololive_dreams';folder.mkdir(parents=True)
        (folder/'launch.json').write_text(json.dumps(PROFILE))
        return GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=Vision([[]],screen()))

    def test_observation_exists_and_missing_game_offers_launch(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'observe'},{'decision':'escalate'}]);agent=self.agent(root,model)
            agent.execute('进入强欲之牌')
            self.assertFalse(model.calls[0]['current_observation']['has_screen'])
            current=model.calls[1]['current_observation']
            self.assertTrue(current['has_screen'])
            self.assertFalse(current['game_running'])
            self.assertEqual(current['launch_option']['skill'],'launch_game')

    def test_old_focus_handle_is_not_dispatched(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'observe'},{'decision':'act','actions':[{'name':'focus','arguments':{'handle':4851280}}]},{'decision':'escalate'}]);agent=self.agent(root,model)
            agent.execute('打开游戏')
            self.assertFalse(any(a.name=='focus' for a in agent.computer.actions))
            self.assertIn('历史句柄',model.calls[2]['recent_results'][-1]['message'])

    def test_invalid_decision_can_be_corrected_without_input(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'nonsense'},{'decision':'escalate','reason':'已修正'}]);agent=self.agent(root,model)
            result=agent.execute('启动游戏')
            self.assertEqual(result['outcome'],'unknown')
            self.assertEqual(model.calls[1]['recent_results'][-1]['decision'],'invalid_output')
            self.assertFalse(agent.computer.actions)
            record=next((Path(root)/'runtime/memory/task_sessions').glob('*.md')).read_text(encoding='utf-8')
            self.assertIn('nonsense',record)

    def test_three_invalid_decisions_stop(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([{'decision':'nonsense'}]*3);agent=self.agent(root,model)
            result=agent.execute('启动游戏')
            self.assertEqual(result['outcome'],'failure')
            self.assertIn('三次',result['message'])
            self.assertFalse(agent.computer.actions)
