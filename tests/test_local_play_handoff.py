import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modular_agent.agent.general import GeneralAgent
from modular_agent.local_models import load_greed_cards_play_module
from test_connected_agent import Computer, Model, PROFILE, GAME
from test_greed_cards_play import BET, HOLD

ROOT=Path(__file__).resolve().parents[1]
MODULE=load_greed_cards_play_module(ROOT)

class LocalPlayHandoffTests(unittest.TestCase):
    def agent(self,root):
        a=GeneralAgent(root,Computer(),Model([]),domain='hololive_dreams')
        a.profiles=[{**PROFILE,'local_models':{'greed_cards_play':{'enabled':True}}}]
        return a
    def report(self):
        from copy import deepcopy
        r=deepcopy(BET);r.windows=[{**GAME,'bounds':r.frame['bounds']}]
        return r

    def test_missing_assets_reject_before_bet_and_metadata_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root)
            with patch('modular_agent.local_models.load_greed_cards_play_module',return_value=MODULE):
                result=agent._local_play_conditions('游玩强欲之牌赚代币',self.report())
            self.assertFalse(result['eligible']);self.assertEqual(len(result['missing_templates']),20)
            self.assertTrue(any(s['skill']=='greed_cards_play' for s in agent._skill_index('hololive_dreams')))
            self.assertFalse(agent.computer.actions)

    def test_same_task_resume_requires_retained_tree_and_same_window(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root)
            with patch('modular_agent.local_models.load_greed_cards_play_module',return_value=MODULE),patch.object(MODULE.CardVision,'missing_assets',return_value=[]):
                r=self.report();r.texts=HOLD.texts
                self.assertFalse(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])
                agent._play_tree=MODULE.GreedCardsPlay();agent._play_window=GAME['handle']
                self.assertTrue(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])
                agent._play_window=999
                self.assertFalse(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])

    def test_explicit_pinyin_play_goal_alias(self):
        for goal in ('wan qiangyuzhipai','wan qiang yu zhi pai','WAN QIANGYUZHIPAI'):
            self.assertTrue(GeneralAgent._play_goal(goal))
        self.assertFalse(GeneralAgent._play_goal('qiangyuzhipai'))
        self.assertFalse(GeneralAgent._play_goal('进入强欲之牌'))
        self.assertFalse(GeneralAgent._play_goal('不要玩强欲之牌'))

    def test_start_conditions_goal_and_midround(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root)
            with patch('modular_agent.local_models.load_greed_cards_play_module',return_value=MODULE),patch.object(MODULE.CardVision,'missing_assets',return_value=[]):
                self.assertTrue(agent._local_play_conditions('游玩强欲之牌',self.report())['eligible'])
                self.assertFalse(agent._local_play_conditions('进入强欲之牌',self.report())['eligible'])
                self.assertFalse(agent._local_play_conditions('不要玩强欲之牌',self.report())['eligible'])
                r=self.report();r.texts=HOLD.texts
                self.assertFalse(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])
                r=self.report();r.windows[0]['foreground']=False
                self.assertFalse(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])

    def test_always_on_top_chat_window_blocks_eligibility(self):
        from modular_agent.perception.report import Rect
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root);r=self.report()
            r.windows[0].update(z_order=2,bounds=Rect(330,167,1161,697).to_dict())
            overlay={'handle':8,'title':'ChatGPT','z_order':1,'foreground':False,
                     'bounds':Rect(1385,0,1177,1601).to_dict()}
            r.windows.append(overlay)
            with patch('modular_agent.local_models.load_greed_cards_play_module',return_value=MODULE),patch.object(MODULE.CardVision,'missing_assets',return_value=[]):
                result=agent._local_play_conditions('游玩强欲之牌',r)
                self.assertFalse(result['eligible'])
                self.assertIn('ChatGPT',result['reason'])
                self.assertEqual(len(MODULE.occluding_windows(r.windows,r.windows[0])),1)
                overlay['z_order']=3
                self.assertTrue(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])
                overlay['z_order']=1;overlay['minimized']=True
                self.assertTrue(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])
                overlay['minimized']=False;overlay['bounds']=Rect(1491,0,100,1601).to_dict()
                self.assertTrue(agent._local_play_conditions('游玩强欲之牌',r)['eligible'])

    def test_done_at_entry_with_blocker_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root);agent.model=Model([{'decision':'observe'},{'decision':'done','reason':'已到下注页，导航完成'}])
            with patch.object(agent,'_observe',return_value=self.report()),patch.object(agent,'_local_play_conditions',return_value={'eligible':False,'reason':'游戏被窗口遮挡：ChatGPT'}):
                result=agent.execute('游玩强 欲之牌')
            self.assertEqual(result['outcome'],'unknown')
            self.assertIn('ChatGPT',result['message'])
            self.assertFalse(result['verified'])

    def test_premature_done_requests_play_and_verified_result_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root);agent.model=Model([{'decision':'observe'},
                {'decision':'done','reason':'入口已完成'},
                {'decision':'use_skill','skill':'greed_cards_play','domain':'hololive_dreams'},
                {'decision':'done','reason':'实际玩法已完成'}])
            local={'outcome':'success','verified':True,'message':'已核对结算'}
            with patch.object(agent,'_observe',return_value=self.report()),patch.object(agent,'_local_play_conditions',return_value={'eligible':True}),patch.object(agent,'_run_local_play',return_value=local):
                result=agent.execute('游玩强欲之牌')
            self.assertEqual(result,local)
            self.assertEqual(agent.model.calls[2]['recent_results'][-1]['decision'],'done_rejected')
            self.assertTrue(agent.model.calls[2]['task_completion']['requires_verified_gameplay'])

    def test_rectangular_overlap_requires_actual_window_hit(self):
        from modular_agent.perception.report import Rect
        game={'handle':7,'source':'win32','z_order':2,'bounds':Rect(0,0,1000,700).to_dict()}
        overlay={'handle':8,'z_order':1,'title':'ChatGPT','bounds':Rect(900,0,500,700).to_dict()}
        windows=[game,overlay]
        self.assertFalse(MODULE.occluding_windows(windows,game,hit_test=lambda x,y:7))
        result=MODULE.occluding_windows(windows,game,hit_test=lambda x,y:8)
        self.assertEqual(result[0]['occlusion_evidence']['method'],'WindowFromPoint')
        self.assertEqual(len(result[0]['occlusion_evidence']['points']),25)
        self.assertFalse(MODULE.occluding_windows(windows,game,hit_test=lambda x,y:0))

    def test_handoff_recaptures_before_run(self):
        with tempfile.TemporaryDirectory() as root:
            agent=self.agent(root)
            r=self.report();r.windows[0]['foreground']=False
            with patch.object(agent,'_observe',return_value=r),patch('modular_agent.local_models.load_greed_cards_play_module',return_value=MODULE):
                with self.assertRaises(ValueError):agent._run_local_play('游玩强欲之牌',lambda _:None,lambda:False)
            self.assertFalse(agent.computer.actions)

if __name__=='__main__':unittest.main()
