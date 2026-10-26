import json
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from modular_agent.agent.general import GeneralAgent
from modular_agent.local_models import load_greed_cards
from modular_agent.perception.report import ScreenReport
from test_connected_agent import Computer, Model, Vision, PROFILE, GAME

ROOT=Path(__file__).resolve().parents[1]
OBSERVE={'decision':'observe'}
LOCAL={'decision':'use_skill','skill':'greed_cards_entry','domain':'hololive_dreams','reason':'当前游戏在前台，自由主界面支持本地导航。'}
END={'decision':'escalate','reason':'交回人工'}

def free_report():
    return ScreenReport(frame={'target_window_handle':7,'detail':'full'},windows=[GAME.copy()],texts=[{'text':w} for w in ['活动','游戏','演出','任务','成就','扭蛋']])

class LocalModelHandoffTests(unittest.TestCase):
    def setup_agent(self,root,model):
        folder=Path(root)/'domains'/'hololive_dreams'
        (folder/'models/greed_cards').mkdir(parents=True)
        shutil.copyfile(ROOT/'domains/hololive_dreams/models/greed_cards/greed_cards_entry.py',folder/'models/greed_cards/greed_cards_entry.py')
        (folder/'launch.json').write_text(json.dumps({**PROFILE,'local_models':{'greed_cards_entry':{'enabled':True}}}))
        return GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=Vision([[GAME]],free_report()))

    def tree(self,root,result):
        tree=MagicMock()
        tree.decide.side_effect=load_greed_cards(root).decide
        tree.run.return_value=result
        return tree

    def test_entry_requires_observation_and_model_selection(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL]);agent=self.setup_agent(root,model)
            tree=self.tree(root,{'outcome':'success','verified':True,'message':'已进入 High&Low'})
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',return_value=free_report()):
                result=agent.execute('打开强欲之牌')
            self.assertTrue(result['verified'])
            self.assertEqual(len(model.calls),2)
            self.assertFalse(model.calls[0]['local_model_conditions']['eligible'])
            self.assertTrue(model.calls[1]['local_model_conditions']['eligible'])
            self.assertIs(tree.run.call_args.args[1],agent.computer)

    def test_unknown_falls_back_with_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL,END]);agent=self.setup_agent(root,model)
            tree=self.tree(root,{'outcome':'unknown','verified':False,'message':'当前游戏场，需要时间设施'})
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',return_value=free_report()): agent.execute('进入强欲之牌')
            self.assertIn('游戏场',model.calls[2]['recent_results'][-1]['result']['message'])
            self.assertFalse(model.calls[2]['local_model_conditions']['eligible'])

    def test_larger_goal_is_not_completed_by_entry(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL,END]);agent=self.setup_agent(root,model)
            tree=self.tree(root,{'outcome':'success','verified':True,'message':'入口导航完成'})
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',return_value=free_report()): result=agent.execute('游玩强欲之牌')
            self.assertEqual(len(model.calls),3)
            self.assertNotEqual(result['outcome'],'success')

    def test_stop_does_not_request_more_model_calls(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL]);agent=self.setup_agent(root,model)
            tree=self.tree(root,{})
            def stop(*args,**kwargs):
                agent.computer.stopped=True
                return {'outcome':'failure','message':'用户停止'}
            tree.run.side_effect=stop
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',return_value=free_report()): result=agent.execute('进入强欲之牌')
            self.assertEqual(result['outcome'],'failure')
            self.assertEqual(len(model.calls),2)

    def test_guidance_survives_handoff(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL,END]);agent=self.setup_agent(root,model)
            queued=[];tree=self.tree(root,{})
            def yield_control(*args,**kwargs):
                queued.append('先不要移动，等我确认')
                self.assertTrue(kwargs['should_yield']())
                return {'outcome':'unknown','message':'人工引导'}
            tree.run.side_effect=yield_control
            def guidance():
                result=queued[:];queued.clear();return result
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',return_value=free_report()): agent.execute('进入强欲之牌',guidance=guidance)
            self.assertEqual(model.calls[2]['human_guidance'][0]['text'],'先不要移动，等我确认')

    def test_preflight_rejects_state_changed_during_model_request(self):
        with tempfile.TemporaryDirectory() as root:
            model=Model([OBSERVE,LOCAL,END]);agent=self.setup_agent(root,model)
            changed=free_report();changed.windows[0]['foreground']=False
            tree=self.tree(root,{'outcome':'success'})
            with patch('modular_agent.local_models.load_greed_cards',return_value=tree),patch.object(agent,'_observe',side_effect=[free_report(),changed]): agent.execute('进入强欲之牌')
            tree.run.assert_not_called()
            self.assertIn('初始条件不满足',model.calls[2]['recent_results'][-1]['message'])

    def test_unknown_background_and_negative_goals_are_ineligible(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.setup_agent(root,Model([]))
            for goal in ('打开其他小游戏','不要进入强欲之牌','介绍强欲之牌'):
                self.assertFalse(agent._local_entry_conditions(goal,free_report())['eligible'])
            unknown=free_report();unknown.texts=[]
            self.assertFalse(agent._local_entry_conditions('进入强欲之牌',unknown)['eligible'])
            hidden=free_report();hidden.windows[0]['foreground']=False
            self.assertFalse(agent._local_entry_conditions('进入强欲之牌',hidden)['eligible'])
