import unittest
from pathlib import Path
from modular_agent.local_models import load_greed_cards
from modular_agent.perception.report import ScreenReport
from test_connected_agent import Computer

ROOT=Path(__file__).resolve().parents[1]

def report(words=(),icons=()):
    return ScreenReport(frame={'target_window_handle':7,'bounds':{'x':0,'y':0,'width':1400,'height':845}},windows=[{'handle':7,'foreground':True}],
        texts=[{'id':'ocr:'+str(i),'text':w,'source':'ocr','bounds':{'x':200+i*40,'y':500,'width':80,'height':25}} for i,w in enumerate(words)],
        knowledge_matches=[{'id':name+str(i),'label':name,'similarity':.9,'bounds':{'x':900 if name=='smallgame' else 180,'y':400+i*80,'width':70,'height':70}} for i,name in enumerate(icons)])

HUD=['活动','游戏','演出','任务','成就','扭蛋']
BET=['High&Low','押注额为50枚代币。','押注并开始游戏','两对以上可获得加倍机会！']

class GreedCardsTreeTests(unittest.TestCase):
    def test_free_main_and_wrong_map(self):
        tree=load_greed_cards(ROOT)
        self.assertEqual(tree.decide(report(HUD))['key'],'m')
        d=tree.decide(report(['MAP','协律花园','满腹之旅','High&Low'],['map2','smallgame']))
        self.assertEqual(d['state'],'select_arcade')
        self.assertEqual(d['target']['label'],'map2')

    def test_region_icon_and_detail_have_correct_priority(self):
        tree=load_greed_cards(ROOT)
        self.assertEqual(tree.decide(report(['MAP','电玩巨蛋城','大厅','游玩区域'],['map2']))['state'],'select_area')
        self.assertEqual(tree.decide(report(['MAP','电玩巨蛋城','游玩区域'],['map2','smallgame']))['state'],'select_smallgame')
        d=tree.decide(report(['MAP','电玩巨蛋城','强欲之牌','猜高低','y移动'],['map2','smallgame']))
        self.assertEqual(d['state'],'teleport')
        self.assertEqual(d['target']['text'],'y移动')

    def test_transient_cruising_can_be_missed(self):
        tree=load_greed_cards(ROOT)
        tree.committed({'state':'teleport'})
        self.assertEqual(tree.decide(report(HUD))['key'],'w')
        self.assertEqual(tree.decide(report(HUD+['猜高低']))['state'],'interact')
        self.assertEqual(tree.decide(report(['Cruising!','移动中']))['state'],'transit')

    def test_success_requires_actual_game_not_map_description(self):
        tree=load_greed_cards(ROOT)
        self.assertEqual(tree.decide(report(BET))['outcome'],'success')
        self.assertNotEqual(tree.decide(report(['MAP','电玩巨蛋城']+BET,['map2'])).get('outcome'),'success')
        self.assertEqual(tree.decide(report(['MAP','电玩巨蛋城','游戏场'],['map2']))['state'],'wrong_time')

    def test_complete_route_without_provider_or_betting(self):
        frames=iter([report(HUD),report(['MAP','协律花园'],['map2']),report(['MAP','电玩巨蛋城','游玩区域'],['map2']),report(['MAP','电玩巨蛋城'],['map2','smallgame']),report(['MAP','电玩巨蛋城','强欲之牌','猜高低','移动'],['map2']),report(HUD),report(HUD+['猜高低']),report(HUD+['Shiori']),report(BET)])
        computer=Computer();tree=load_greed_cards(ROOT)
        result=tree.run(lambda:next(frames),computer)
        self.assertEqual(result['outcome'],'success')
        self.assertTrue(result['verified'])
        presses=[a.arguments['key'] for a in computer.actions if a.name=='press']
        self.assertEqual(presses,['m','w','e'])
        self.assertTrue(all(a.arguments['modifiers']==['alt'] for a in computer.actions if a.name=='click'))
        self.assertGreater(computer.releases,0)

    def test_stuck_state_stops_repeating_and_releases(self):
        tree=load_greed_cards(ROOT);computer=Computer()
        result=tree.run(lambda:report(HUD),computer)
        self.assertEqual(result['outcome'],'unknown')
        self.assertEqual(sum(a.name=='press' for a in computer.actions),3)
        self.assertGreater(computer.releases,0)

    def test_unknown_and_cancellation_send_no_input(self):
        tree=load_greed_cards(ROOT);computer=Computer()
        computer.stopped=True
        self.assertEqual(tree.run(lambda:report(HUD),computer)['outcome'],'failure')
        self.assertFalse(computer.actions)
        self.assertEqual(tree.decide(report(['unknown']))['outcome'],'unknown')

    def test_shiori_dialogue_resumes_with_e_and_is_bounded(self):
        tree=load_greed_cards(ROOT)
        frame=report(HUD+['Shiori','为了抓住机会，尽力而为吧！'])
        for attempt in range(2):
            decision=tree.decide(frame)
            self.assertEqual(decision['state'],'dialogue')
            self.assertEqual(decision['key'],'e')
            tree.committed(decision)
        self.assertEqual(tree.decide(frame)['outcome'],'unknown')
        self.assertEqual(tree.decide(report(BET))['outcome'],'success')
