import unittest
from test_greed_cards_tree import ROOT, HUD, BET, report
from test_connected_agent import Computer
from modular_agent.local_models import load_greed_cards

class EntryTransitions(unittest.TestCase):
    def test_panned_map(self):
        tree=load_greed_cards(ROOT);r=report(['MAP','电玩巨蛋城'],['smallgame'])
        r.knowledge_matches[0]['bounds']['x']=300
        self.assertEqual(tree.decide(r)['state'],'select_smallgame')

    def test_no_dialogue_restart(self):
        tree=load_greed_cards(ROOT);tree.committed({'state':'interact'})
        for words in (HUD,HUD+['猜高低']):
            self.assertEqual(tree.decide(report(words))['action'],'wait')

    def test_lever(self):
        tree=load_greed_cards(ROOT)
        d=tree.decide(report(['MAP','电玩巨蛋城','游戏区','大厅']))
        self.assertEqual(d['state'],'select_lobby');tree.committed(d)
        self.assertEqual(tree.decide(report(['MAP','电玩巨蛋城','大厅','游玩区域'],['time']))['state'],'select_lever')
        self.assertEqual(tree.decide(report(HUD+['切换操纵杆']))['key'],'e')
        d=tree.decide(report(HUD+['切换为赌场区','不进行更改']))
        self.assertEqual(d['state'],'switch_casino');tree.committed(d)
        self.assertEqual(tree.decide(report(HUD))['state'],'open_map_after_switch')

    def test_loading(self):
        frames=iter([report(['MAP','电玩巨蛋城','强欲之牌','猜高低','移动']),*[report() for _ in range(6)],report(BET)])
        ticks=iter(range(100));computer=Computer()
        result=load_greed_cards(ROOT).run(lambda:next(frames),computer,clock=lambda:next(ticks))
        self.assertEqual(result['outcome'],'success')
        self.assertEqual(result['next_module'],'greed_cards_play')
        self.assertFalse(any(a.name=='press' for a in computer.actions))

    def test_timeout(self):
        ticks=iter(range(100));computer=Computer()
        result=load_greed_cards(ROOT).run(lambda:report(),computer,clock=lambda:next(ticks),transition_timeout=5)
        self.assertEqual(result['outcome'],'unknown')
        self.assertFalse(any(a.name in ('click','press') for a in computer.actions))
