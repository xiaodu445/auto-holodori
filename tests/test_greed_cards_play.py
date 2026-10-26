import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from modular_agent.local_models import load_greed_cards_play_module, play_starting_policy, save_play_result
from modular_agent.perception.report import ScreenReport, Rect
from modular_agent.core import Outcome, SkillResult

ROOT=Path(__file__).resolve().parents[1]
M=load_greed_cards_play_module(ROOT)
# Historical screenshots/templates span several window sizes. Production uses [1].
HISTORICAL_PROFILE={'local_models':{'greed_cards_play':{'template_scales':[.45,.5,.55,.58,.6,.62,.65,.67,.7,.75,.8,.85,.9,1.,1.25,1.5]}}}

def report(*words):
    return ScreenReport(frame={'target_window_handle':7,'bounds':Rect(0,0,1400,835).to_dict()},
        windows=[{'handle':7,'foreground':True}],
        texts=[{'text':w,'confidence':.99,'bounds':Rect(100+i*100,100,80,25).to_dict()} for i,w in enumerate(words)])

def cards(ranks=(13,10,13,5,12),held=()):
    suits=['spade','club','club','diamond','heart']
    return [{'rank':r,'suit':suits[i] if r else 'joker','held':i in held,'bounds':Rect(100+i*220,300,200,285).to_dict()} for i,r in enumerate(ranks)]

BET=report('High&Low','押注额为50枚代币。','押注并开始游戏')
HOLD=report('请选择要留下的卡片！','替换')
GUESS=report('你觉得下一张的数值比翻开的牌高还是低？','数字一样就再来一次','高','《低')

def challenge(next_amount):
    return report('成功！','连续成功的话，获得额会变成'+str(next_amount)+'哦！','是否挑战？','× 算了','挑战')

def settled(amount):
    return report('获得了'+str(amount)+'枚代币','要再玩一次扑克吗？','再来一次','算了')

class Computer:
    live=True
    stopped=False
    def __init__(self):self.actions=[];self.releases=0
    def run_actions(self,actions):
        self.actions.extend(actions)
        return [SkillResult(Outcome.SUCCESS) for a in actions]
    def release_all(self):self.releases+=1

class GameplayTests(unittest.TestCase):
    def test_user_baseline_and_guaranteed_reward(self):
        self.assertEqual(M.choose_hold(cards()),(0,2))
        self.assertEqual(M.choose_hold(cards((0,7,7,8,9))),tuple(range(5)))
        self.assertEqual(M.choose_hold(cards((4,4,9,9,13))),(0,1,2,3))
        self.assertTrue(M.rewarded(cards((0,7,7,8,9))))

    def test_keep_all_confirmation_and_two_pair_replaces_kicker(self):
        keep_all=report('请选择要留下的卡片！','现在这样就好')
        self.assertEqual(M.classify(keep_all),'hold')
        tree=M.GreedCardsPlay();tree.round_active=True
        straight=cards((2,3,4,5,6),held=range(5))
        decision=tree.decide(keep_all,straight)
        self.assertEqual(decision['kind'],'replace')
        self.assertEqual(decision['target'],M.label(keep_all,'现在这样就好')['bounds'])
        tree.committed(decision)
        self.assertEqual(tree.decide(keep_all,straight)['action'],'wait')
        tree=M.GreedCardsPlay();tree.round_active=True
        decision=tree.decide(keep_all,cards((4,4,9,9,13),held=range(5)))
        self.assertEqual(decision['kind'],'hold')
        self.assertEqual(decision['index'],4)
        self.assertFalse(decision['held'])
        tree.committed(decision)
        decision=tree.decide(HOLD,cards((4,4,9,9,13),held=(0,1,2,3)))
        self.assertEqual(decision['target'],M.label(HOLD,'替换')['bounds'])
        self.assertEqual(decision['kind'],'replace')

    def test_sqrt_prefixed_challenge_label_and_animation_wait(self):
        r=challenge(800);r.texts[-1]['text']='√挑战'
        self.assertIsNotNone(M.label(r,'挑战'))
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        hidden=challenge(800);hidden.texts.pop()
        decision=tree.decide(hidden)
        self.assertEqual(decision['action'],'wait')
        self.assertEqual(decision['waiting_for'],'挑战')
        self.assertIsNone(tree.pending)
        self.assertEqual(tree.decide(r)['kind'],'challenge')
        computer=Computer();frames=iter([hidden,r])
        def observe():
            try: return {'report':next(frames)}
            except StopIteration:
                computer.stopped=True
                return {'report':r}
        tree.run(observe,computer)
        self.assertEqual(sum(a.name=='click' for a in computer.actions),1)
        self.assertEqual(computer.actions[0].name,'wait')

    def test_missing_button_wait_is_bounded_without_clicks(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        hidden=challenge(800);hidden.texts.pop()
        computer=Computer();now=[0]
        def observe(): now[0]+=3;return {'report':hidden}
        result=tree.run(observe,computer,clock=lambda:now[0])
        self.assertEqual(result['outcome'],'unknown')
        self.assertIn('挑战',result['message'])
        self.assertFalse(any(a.name=='click' for a in computer.actions))
        self.assertEqual(computer.releases,1)

    def test_select_one_card_then_verify_not_repeat(self):
        tree=M.GreedCardsPlay();d=tree.decide(BET);tree.committed(d)
        d=tree.decide(HOLD,cards());self.assertEqual(d['index'],0);tree.committed(d)
        self.assertEqual(tree.decide(HOLD,cards())['action'],'wait')
        d=tree.decide(HOLD,cards(held=(0,)));self.assertEqual(d['index'],2);tree.committed(d)
        d=tree.decide(HOLD,cards(held=(0,2)));self.assertEqual(d['kind'],'replace');tree.committed(d)
        self.assertEqual(tree.decide(HOLD,cards(held=(0,2)))['action'],'wait')
        self.assertEqual(tree.fees,50)

    def test_guess_threshold_and_amount_validation(self):
        for rank,expected in [(2,'高'),(7,'高'),(8,'高'),(9,'《低'),(14,'《低')]:
            tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
            d=tree.decide(GUESS,[{'rank':rank}]);self.assertEqual(d['target'],M.label(GUESS,expected.strip('《'))['bounds'])
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        d=tree.decide(GUESS,[{'rank':8}]);tree.committed(d)
        self.assertEqual(tree.decide(GUESS,[{'rank':8}])['action'],'wait')
        d=tree.decide(challenge(1600));self.assertEqual(tree.current,800)
        self.assertEqual(d['kind'],'challenge')
        # A repeated success popup must not double again.
        tree.committed(d);tree.decide(challenge(1600));self.assertEqual(tree.current,800)

    def test_cashout_confirmed_twice_and_daily_overshoot(self):
        tree=M.GreedCardsPlay(daily_collected=19200,stage=2)
        tree.round_active=True;tree.current=12800
        d=tree.decide(challenge(25600));self.assertEqual(d['kind'],'cashout');tree.committed(d)
        self.assertEqual(tree.decide(settled(12800))['action'],'wait');self.assertEqual(tree.daily,19200)
        d=tree.decide(settled(12800));self.assertEqual(d['outcome'],'success');self.assertEqual(tree.daily,32000)
        tree.decide(settled(12800));self.assertEqual(tree.daily,32000)

    def test_final_win_automatic_settlement_and_mismatch(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=6400
        tree.committed(tree.decide(GUESS,[{'rank':3}]))
        self.assertEqual(tree.decide(settled(12800))['action'],'wait');self.assertEqual(tree.current,12800)
        tree.decide(settled(12800));self.assertEqual(tree.daily,12800)
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        tree.committed(tree.decide(GUESS,[{'rank':3}]))
        self.assertEqual(tree.decide(challenge(1200))['outcome'],'unknown')

    def test_stage_one_stops_at_6400_and_preserves_last_round(self):
        tree=M.GreedCardsPlay(daily_collected=12800,stage=1);tree.round_active=True
        self.assertEqual(tree.decide(challenge(12800))['kind'],'cashout')
        tree=M.GreedCardsPlay(daily_collected=15000,stage=1);tree.round_active=True
        self.assertEqual(tree.decide(challenge(8000))['kind'],'cashout')

    def test_missing_template_midround_budget_and_failure_are_handoffs(self):
        tree=M.GreedCardsPlay(daily_collected=None)
        self.assertEqual(tree.decide(BET)['outcome'],'unknown')
        tree=M.GreedCardsPlay()
        self.assertEqual(tree.decide(HOLD,cards())['outcome'],'unknown')
        self.assertEqual(tree.decide(HOLD,cards(),['missing'])['outcome'],'unknown')
        tree.rounds=20;self.assertEqual(tree.decide(BET)['outcome'],'unknown')
        tree=M.GreedCardsPlay();tree.round_active=True
        d=tree.decide(report('失败','要再玩一次扑克吗？','再来一次'));self.assertEqual(d['kind'],'retry')
        self.assertFalse(tree.round_active)

    def test_stop_guidance_release_and_stuck_consumption(self):
        for stopped,guidance in [(True,False),(False,True)]:
            c=Computer();c.stopped=stopped
            r=M.GreedCardsPlay().run(lambda:{'report':BET},c,should_yield=lambda:guidance)
            self.assertFalse(r['verified']);self.assertFalse(c.actions);self.assertEqual(c.releases,1)
        c=Computer();now=[0]
        def observe():now[0]+=3;return {'report':BET}
        r=M.GreedCardsPlay().run(observe,c,clock=lambda:now[0])
        self.assertEqual(sum(a.name=='click' for a in c.actions),1)
        self.assertEqual(r['outcome'],'unknown')
        self.assertEqual(next(a for a in c.actions if a.name=='click').arguments['modifiers'],['alt'])

    def test_ledger_persistence_same_day_and_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_play_result(tmp,{'ledger':{'daily_collected':12800,'stage':1}})
            self.assertEqual(play_starting_policy(tmp)['daily_collected'],12800)
            with patch('modular_agent.local_models.play_day',return_value='2099-01-01'):
                self.assertEqual(play_starting_policy(tmp)['daily_collected'],0)
            self.assertEqual(play_starting_policy(tmp,123,2)['stage'],2)

    def test_complete_verified_route_single_round(self):
        observations=[{'report':BET}, {'report':HOLD,'cards':cards()},
            {'report':HOLD,'cards':cards(held=(0,))},
            {'report':HOLD,'cards':cards(held=(0,2))}, {'report':challenge(400)}]
        # Six independently confirmed wins turn 200 into 12800.
        for cash in (200,400,800,1600,3200,6400):
            observations.append({'report':GUESS,'cards':[{'rank':2,'suit':'spade'}]})
            if cash<6400: observations.append({'report':challenge(cash*4)})
        observations.extend([{'report':settled(12800)},{'report':settled(12800)}])
        frames=iter(observations);computer=Computer()
        result=M.GreedCardsPlay(daily_collected=19200,stage=2).run(lambda:next(frames),computer)
        self.assertEqual(result['outcome'],'success')
        self.assertEqual(result['ledger']['daily_collected'],32000)
        self.assertEqual(result['ledger']['entry_fees'],50)
        self.assertEqual(sum(a.name=='click' for a in computer.actions),16)
        self.assertEqual(computer.releases,1)

    def test_confirmed_tie_does_not_double(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        tree.committed(tree.decide(GUESS,[{'rank':8,'suit':'spade'}]))
        decision=tree.decide(GUESS,[{'rank':8,'suit':'heart'}])
        self.assertEqual(decision['kind'],'guess')
        self.assertEqual(tree.current,400)

    def test_ocr_button_fallback_requires_current_confident_template(self):
        r=report('公高');r.texts[0]['confidence']=.69
        self.assertIsNone(M.label(r,'高'))
        r.knowledge_matches=[{'label':'hl_button_high','similarity':.9,'bounds':Rect(900,300,200,80).to_dict()}]
        self.assertEqual(M.label(r,'高')['bounds']['x'],900)
        r.knowledge_matches[0]['similarity']=M.TEMPLATE_THRESHOLD
        self.assertIsNotNone(M.label(r,'高'))
        r.knowledge_matches[0]['similarity']=M.TEMPLATE_THRESHOLD-.01
        self.assertIsNone(M.label(r,'高'))

    def test_real_selection_badges_and_coordinate_origin(self):
        from modular_agent.perception.screen import load_image
        image=load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/hold_selected.png')
        with tempfile.TemporaryDirectory() as tmp:
            vision=M.CardVision(tmp)
            replies=[]
            for rank,suit in [('9','diamond'),('2','diamond'),('4','diamond'),('8','spade'),('6','diamond')]:
                replies.extend([(None,0),(None,0),('hl_rank_'+rank,.95),('hl_suit_'+suit,.95)])
            with patch.object(vision,'missing',return_value=[]),patch.object(vision,'match',side_effect=replies):
                found,errors=vision.read(image,(-500,20),'hold')
            self.assertFalse(errors)
            self.assertEqual([c['held'] for c in found],[False,True,True,False,True])
            import json
            self.assertTrue(all(type(c['held']) is bool for c in found))
            self.assertEqual(json.loads(json.dumps(found)),found)
            self.assertEqual(found[0]['bounds']['x'],107-500)
            self.assertEqual(found[0]['bounds']['y'],295+20)

    def test_reported_live_hand_rank_and_suit_regression(self):
        from modular_agent.perception.screen import load_image
        vision=M.CardVision(ROOT/'domains/hololive_dreams/data/high_low_templates')
        if vision.missing(): self.skipTest('用户完整卡牌模板未提供')
        found,errors=vision.read(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/hold_20261002_184348.png'),(269,98),'hold')
        self.assertFalse(errors)
        self.assertEqual([(c['rank'],c['suit']) for c in found],[(13,'heart'),(9,'diamond'),(14,'diamond'),(10,'heart'),(11,'spade')])
        self.assertTrue(all(c['score']>=M.TEMPLATE_THRESHOLD for c in found))
        self.assertEqual(found[1]['bounds']['x'],568)

    def test_full_card_joker_template_and_no_ordinary_false_positive(self):
        from modular_agent.perception.screen import load_image
        vision=M.CardVision(ROOT/'domains/hololive_dreams/data/high_low_templates')
        if vision.missing(): self.skipTest('用户完整卡牌模板未提供')
        found,errors=vision.read(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/hold_20261002_185036_joker.png'),(269,98),'hold')
        self.assertFalse(errors)
        self.assertEqual([(c['rank'],c['suit']) for c in found],[(6,'heart'),(13,'heart'),(8,'heart'),(0,'joker'),(5,'diamond')])
        self.assertGreaterEqual(found[3]['score'],M.TEMPLATE_THRESHOLD)
        ordinary,errors=vision.read(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/hold_20261002_184348.png'),(0,0),'hold')
        self.assertFalse(errors)
        self.assertFalse(any(c['rank']==0 for c in ordinary))

    def test_zero_candidate_margin_is_allowed_above_threshold(self):
        import numpy as np
        import cv2
        with tempfile.TemporaryDirectory() as folder:
            vision=M.CardVision(folder)
            image=np.full((40,40,3),255,dtype=np.uint8)
            cv2.circle(image,(20,20),10,(0,0,0),-1)
            mask=vision.glyph(image)
            vision.templates={'hl_suit_spade':[mask],'hl_suit_club':[mask]}
            name,score=vision.match(image,['hl_suit_spade','hl_suit_club','hl_suit_diamond','hl_suit_heart'])
            self.assertEqual(name,'hl_suit_spade')
            self.assertEqual(vision.last_match['margin'],0)
            self.assertGreaterEqual(score,M.TEMPLATE_THRESHOLD)

    def test_actual_screenshot_boxes_and_missing_materials(self):
        from modular_agent.perception.screen import load_image
        folder=ROOT/'domains/hololive_dreams/data/high_low_samples'
        for name,count in [('hold_selected',5),('hold_unselected',5),('guess',1),('challenge_success',0)]:
            image=load_image(folder/(name+'.png'))
            self.assertEqual(len(M.CardVision.boxes(image)),count)
        with tempfile.TemporaryDirectory() as tmp:
            vision=M.CardVision(tmp)
            self.assertEqual(len(vision.missing()),18)
            image=load_image(folder/'hold_unselected.png')
            found,errors=vision.read(image,(0,0),'hold')
            self.assertFalse(found);self.assertTrue(errors)

    def test_stacked_guess_uses_current_rightmost_card(self):
        from modular_agent.perception.screen import load_image
        vision=M.CardVision(ROOT/'domains/hololive_dreams/data/high_low_templates')
        if vision.missing(): self.skipTest('用户完整卡牌模板未提供')
        image=load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/guess_stacked_20261002.png')
        self.assertEqual(len(vision.boxes(image)),2)
        found,errors=vision.read(image,(269,98),'guess')
        self.assertFalse(errors)
        self.assertEqual([(c['rank'],c['suit']) for c in found],[(4,'heart')])
        self.assertEqual(found[0]['bounds']['x'],490)
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=200
        tree.committed(tree.decide(GUESS,[{'rank':6,'suit':'diamond'}]))
        self.assertEqual(tree.decide(GUESS,found)['action'],'wait')

    def test_missing_guess_face_waits_without_repeating_input(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            found,errors=M.CardVision(tmp).read(np.zeros((700,1160,3),dtype=np.uint8),(0,0),'guess')
        self.assertFalse(found)
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=200
        self.assertEqual(tree.decide(GUESS,found,errors)['action'],'wait')
        tree.committed(tree.decide(GUESS,[{'rank':6,'suit':'diamond'}]))
        pending=tree.pending.copy()
        self.assertEqual(tree.decide(GUESS,found,errors)['action'],'wait')
        self.assertEqual(tree.pending,pending)
        self.assertEqual(tree.decide(GUESS,[],['点数置信不足'])['outcome'],'unknown')

    def test_live_queen_guess_passes_gameplay_threshold(self):
        from modular_agent.perception.screen import load_image
        vision=M.CardVision(ROOT/'domains/hololive_dreams/data/high_low_templates')
        if vision.missing(): self.skipTest('用户完整卡牌模板未提供')
        found,errors=vision.read(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/guess_q_20261003.png'),(0,0),'guess')
        self.assertFalse(errors)
        self.assertEqual([(c['rank'],c['suit']) for c in found],[(12,'diamond')])
        self.assertGreaterEqual(found[0]['score'],.5)

    def test_retry_ignores_old_guess_background_until_bet(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        tree.committed(tree.decide(GUESS,[{'rank':13,'suit':'heart'}]))
        decision=tree.decide(report('失败','没能拿到代币','要再玩一次扑克吗？','再来一次'))
        self.assertEqual(decision['kind'],'retry')
        tree.committed(decision)
        for state_report in (GUESS,challenge(800),HOLD):
            self.assertEqual(tree.decide(state_report,[],['过渡牌面不完整'])['action'],'wait')
            self.assertEqual(tree.pending['kind'],'retry')
            self.assertFalse(tree.round_active)
        decision=tree.decide(BET)
        self.assertEqual(decision['kind'],'bet')
        tree.committed(decision)
        tree.decide(HOLD,cards())
        self.assertTrue(tree.round_active)
        self.assertEqual(tree.fees,50)

    def test_retry_supplements_wait_for_interval_and_count_only_commits(self):
        tree=M.GreedCardsPlay();tree.round_active=True
        failure=report('失败','没能拿到代币','要再玩一次扑克吗？','再来一次')
        with patch.object(M.time,'monotonic',return_value=0):
            tree.committed(tree.decide(failure))
        with patch.object(M.time,'monotonic',return_value=.49):
            self.assertEqual(tree.decide(failure)['action'],'wait')
        for now in (1,2,3):
            with patch.object(M.time,'monotonic',return_value=now):
                decision=tree.decide(failure)
                self.assertEqual(decision['kind'],'retry')
                self.assertEqual(tree.decide(failure)['kind'],'retry')
                tree.committed(decision)
        self.assertEqual(tree.retry_clicks,3)
        with patch.object(M.time,'monotonic',return_value=4):
            self.assertEqual(tree.decide(failure)['action'],'wait')
        self.assertEqual(tree.decide(BET)['kind'],'bet')

    def test_all_button_actions_supplement_with_fresh_target_and_limit(self):
        cases=[('bet',BET,[]),('replace',HOLD,cards(held=(0,2))),
               ('challenge',challenge(800),[]),('cashout',challenge(25600),[]),
               ('proceed',report('Congratulations!','点击继续'),[]),
               ('guess',GUESS,[{'rank':8,'suit':'spade'}])]
        for kind,screen,hand in cases:
            with self.subTest(kind=kind):
                tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
                decision={'kind':kind,'state':M.classify(screen)}
                if kind=='guess': decision['basis']=(8,'spade')
                with patch.object(M.time,'monotonic',return_value=0): tree.committed(decision)
                with patch.object(M.time,'monotonic',return_value=.4):
                    self.assertEqual(tree.decide(screen,hand)['action'],'wait')
                for now in (1,2,3):
                    with patch.object(M.time,'monotonic',return_value=now):
                        retry=tree.decide(screen,hand)
                        self.assertEqual(retry['kind'],kind)
                        self.assertTrue(retry['supplement'])
                        tree.committed(retry)
                with patch.object(M.time,'monotonic',return_value=4):
                    self.assertEqual(tree.decide(screen,hand)['action'],'wait')

    def test_settlement_bad_amount_waits_without_changing_ledger(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=6400
        tree.committed(tree.decide(GUESS,[{'rank':13,'suit':'heart'}]))
        for amount in (None,2560,1280):
            screen=report();screen.frame.update(high_low_template_state='settlement',high_low_settlement_amount=amount)
            self.assertEqual(tree.decide(screen)['action'],'wait')
            self.assertEqual(tree.current,6400)
            self.assertEqual(tree.guess_wins,0)
            self.assertEqual(tree.pending['kind'],'guess')
        screen=report();screen.frame.update(high_low_template_state='settlement',high_low_settlement_amount=12800)
        self.assertEqual(tree.decide(screen)['action'],'wait')
        self.assertEqual(tree.current,12800)
        self.assertEqual(tree.guess_wins,1)
        tree.decide(screen)
        self.assertEqual(tree.earned,12800)
        self.assertEqual(tree.guess_wins,1)

    def test_manual_daily_collected_selects_cashout_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(play_starting_policy(folder,12800)['stage'],1)
            self.assertEqual(play_starting_policy(folder,19200)['stage'],2)
            self.assertEqual(play_starting_policy(folder,0)['stage'],0)
            self.assertEqual(play_starting_policy(folder,12800,stage=2)['stage'],2)
            policy=play_starting_policy(folder,12800)
            tree=M.GreedCardsPlay(**policy);tree.round_active=True;tree.current=6400
            self.assertEqual(tree.decide(challenge(12800))['kind'],'cashout')
            with self.assertRaises(ValueError): play_starting_policy(folder,-1)

    def test_hold_uncertain_cards_wait_and_complete_duplicates_proceed(self):
        tree=M.GreedCardsPlay();tree.round_active=True
        decision=tree.decide(HOLD,cards()[:4],['第3张无法分离普通角标','检测到重复牌，拒绝决策'])
        self.assertEqual(decision['action'],'wait')
        self.assertTrue(decision['card_retry'])
        hand=cards();hand[2]['suit']=hand[0]['suit']
        self.assertEqual(tree.decide(HOLD,hand,['检测到重复牌，拒绝决策'])['action'],'click')

    def test_daily_remainder_below_2000_pursues_final_large_reward(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(play_starting_policy(folder,19000)['stage'],2)
            self.assertEqual(play_starting_policy(folder,18000)['stage'],1)
        tree=M.GreedCardsPlay(daily_collected=19000,stage=1)
        tree.round_active=True;tree.current=800
        self.assertEqual(tree.decide(challenge(1600))['kind'],'challenge')
        self.assertEqual(tree.stage,2)
        tree.current=6400
        self.assertEqual(tree.decide(challenge(12800))['kind'],'challenge')
        tree.current=12800
        self.assertEqual(tree.decide(challenge(25600))['kind'],'cashout')

    def test_round_profit_logs_count_failure_once(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.rounds=1;tree.fees=50
        failure=report('失败','没能拿到代币','要再玩一次扑克吗？','再来一次')
        tree.decide(failure);tree.decide(failure)
        self.assertEqual(tree.ledger()['lost_rounds'],1)
        self.assertEqual(tree.ledger()['loss_amount'],50)
        self.assertEqual(tree.ledger()['round_history'][0]['net'],-50)
        tree.round_active=True;tree.rounds=2;tree.fees=100;tree.current=6400
        screen=report();screen.frame.update(high_low_template_state='settlement',high_low_settlement_amount=6400)
        tree.decide(screen);tree.decide(screen)
        self.assertEqual(tree.ledger()['winning_net'],6350)
        self.assertEqual(tree.ledger()['net'],6300)
        with tempfile.TemporaryDirectory() as folder:
            save_play_result(folder,{'ledger':tree.ledger()})
            self.assertIn('净收益-50',(Path(folder)/'runtime/high-low/runs.log').read_text(encoding='utf-8'))

    def test_accounted_settlement_waits_for_retry_without_double_accounting(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=12800
        screen=report();screen.frame.update(high_low_template_state='settlement',high_low_settlement_amount=12800)
        tree.decide(screen)
        for _ in range(5):
            decision=tree.decide(screen)
            self.assertEqual(decision['action'],'wait')
            self.assertEqual(tree.earned,12800)
            self.assertEqual(tree.cashouts,1)
            self.assertEqual(len(tree.round_history),1)
        ready=report('再来一次');ready.frame.update(high_low_template_state='settlement',high_low_settlement_amount=12800)
        decision=tree.decide(ready)
        self.assertEqual(decision['kind'],'retry')
        tree.committed(decision)
        self.assertEqual(tree.decide(BET)['kind'],'bet')
        self.assertFalse(tree.settlement_accounted)

    def test_daily_restore_falls_back_to_log_and_survives_checkpoint(self):
        from modular_agent.local_models import save_play_checkpoint
        with tempfile.TemporaryDirectory() as folder:
            save_play_result(folder,{'ledger':{'daily_collected':12800,'stage':1}})
            path=Path(folder)/'runtime/high-low/last-result.json'
            path.write_text('{broken',encoding='utf-8')
            self.assertEqual(play_starting_policy(folder)['daily_collected'],12800)
            with path.with_name('runs.jsonl').open('a',encoding='utf-8') as f: f.write('broken line\n')
            self.assertEqual(play_starting_policy(folder)['stage'],1)
            save_play_checkpoint(folder,{'daily_collected':19200,'stage':2})
            self.assertEqual(play_starting_policy(folder)['daily_collected'],19200)

    def test_failure_button_loading_does_not_lose_context(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        self.assertEqual(tree.decide(report('失败','没能拿到代币','要再玩一次扑克吗？'))['action'],'wait')
        self.assertEqual(tree.decide(GUESS,[],['过渡牌面'])['action'],'wait')
        self.assertEqual(tree.decide(report('失败','没能拿到代币','要再玩一次扑克吗？','再来一次'))['kind'],'retry')

    def test_actual_reward_panel_amount_and_retry_wording(self):
        panel=report('获得代币','12800枚','得分牌型','两对','加倍','6次','再玩一次')
        self.assertEqual(M.classify(panel),'settlement')
        self.assertEqual(M.settlement_amount(panel),12800)
        self.assertIsNotNone(M.label(panel,'再来一次'))
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=6400
        tree.committed(tree.decide(GUESS,[{'rank':2,'suit':'spade'}]))
        self.assertEqual(tree.decide(panel)['action'],'wait')
        decision=tree.decide(panel)
        self.assertEqual(decision['kind'],'retry')
        self.assertEqual(tree.daily,12800)
        tree.committed(decision)
        self.assertEqual(tree.decide(GUESS)['action'],'wait')
        self.assertEqual(tree.decide(BET)['kind'],'bet')

    def test_reward_panel_end_confirms_stop_without_duplicate_credit(self):
        panel=report('获得代币','6400枚','得分牌型','两对','加倍','结束')
        tree=M.GreedCardsPlay(daily_collected=12800);tree.round_active=True;tree.current=6400
        self.assertEqual(tree.decide(panel)['action'],'wait')
        self.assertEqual(tree.decide(panel)['outcome'],'success')
        self.assertEqual(tree.daily,19200)
        self.assertEqual(tree.decide(panel)['outcome'],'unknown')
        self.assertEqual(tree.daily,19200)

    def test_statistics_count_only_confirmed_wins_and_cashouts(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=200
        tree.committed(tree.decide(GUESS,[{'rank':2,'suit':'spade'}]))
        tree.decide(challenge(800))
        self.assertEqual(tree.ledger()['guess_wins'],1)
        tree.decide(challenge(800))
        self.assertEqual(tree.ledger()['guess_wins'],1)
        tree.fees=50
        tree.decide(settled(400));tree.decide(settled(400))
        self.assertEqual(tree.ledger()['cashouts'],1)
        self.assertEqual(tree.ledger()['return_on_fees'],7)
        self.assertEqual(tree.ledger()['guess_win_rate'],1)

    def test_template_guess_and_hold_skip_ocr(self):
        from modular_agent.perception import GeneralVision
        from modular_agent.perception.screen import load_image
        observer=M.PlayObserver(ROOT,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,HISTORICAL_PROFILE)
        with patch.object(observer,'_ocr',side_effect=AssertionError('normal template path must not call OCR')):
            for name,phase in [('hold_unselected.png','hold'),('guess_q_20261003.png','guess')]:
                result=observer.analyze(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples'/name))
                self.assertEqual(M.classify(result['report']),phase)
                self.assertFalse(result['errors'])
                if phase=='guess':
                    self.assertIsNotNone(M.label(result['report'],'高'))
                    self.assertIsNotNone(M.label(result['report'],'低'))

    def test_missing_template_episode_uses_ocr_once_and_logs(self):
        import numpy as np
        from modular_agent.perception import GeneralVision
        with tempfile.TemporaryDirectory() as root:
            observer=M.PlayObserver(root,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,{})
            empty=report('动画过渡')
            with patch.object(observer,'_ocr',return_value=empty) as ocr:
                with patch.object(M.time,'monotonic',side_effect=[0,0,0,1,1,1,2.1,2.1,2.1,3,3,3]):
                    for _ in range(4): observer.analyze(np.zeros((724,1208,3),dtype=np.uint8))
            self.assertEqual(ocr.call_count,1)
            import json
            logs=(Path(root)/'runtime/high-low/ocr-fallbacks.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(logs),1)
            entry=json.loads(logs[0])
            self.assertEqual(entry['reason'],'state_missing')
            self.assertEqual(entry['missing_predicates']['hl_state_reveal']['reason'],'missing_file')

    def test_template_reveal_clicks_current_window_center(self):
        tree=M.GreedCardsPlay();tree.round_active=True
        r=report();r.frame['high_low_template_state']='reveal';r.frame['high_low_reward_amount']=200
        r.frame['bounds']=Rect(-500,50,1208,724).to_dict()
        decision=tree.decide(r)
        self.assertEqual(decision['kind'],'proceed')
        self.assertEqual(decision['target']['x'],99)
        self.assertEqual(tree.current,200)

    def test_one_pair_failure_does_not_misclassify_challenge(self):
        from modular_agent.perception import GeneralVision
        from modular_agent.perception.screen import load_image
        observer=M.PlayObserver(ROOT,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,HISTORICAL_PROFILE)
        with patch.object(observer,'_ocr',side_effect=AssertionError('failure buttons suffice')):
            result=observer.analyze(load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/failure_one_pair_20261006.png'))
        self.assertEqual(M.classify(result['report']),'failure')
        self.assertIsNone(M.label(result['report'],'挑战'))
        tree=M.GreedCardsPlay();tree.round_active=True
        tree.pending={'kind':'replace','state':'hold'}
        self.assertEqual(tree.decide(result['report'])['kind'],'retry')
        self.assertEqual(tree.current,0)

    def test_spatially_competing_matches_accept_clear_winner(self):
        reason=M.PlayObserver.spatial_match_reason
        self.assertEqual(reason(.870229,.556624),'matched')
        self.assertEqual(reason(.87,.82),'ambiguous')
        self.assertEqual(reason(.65,.5),'matched')
        self.assertEqual(reason(.649,.5),'ambiguous')
        self.assertEqual(reason(.5,.49),'matched')
        self.assertEqual(reason(.49,.2),'below_threshold')

    def test_replace_waits_for_result_and_cannot_jump_back_to_bet(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=None
        tree.pending={'kind':'replace','state':'hold'}
        for r in (BET,report('未知动画')):
            decision=tree.decide(r)
            self.assertEqual(decision['action'],'wait')
            self.assertEqual(tree.pending['kind'],'replace')
            self.assertTrue(tree.round_active)
        failure=report('真可惜','要再玩一次扑克吗？','再来一次')
        self.assertEqual(tree.decide(failure)['kind'],'retry')

    def test_active_round_without_pending_never_bets_again(self):
        tree=M.GreedCardsPlay();tree.round_active=True;tree.current=400
        self.assertEqual(tree.decide(BET)['action'],'wait')
        self.assertEqual(tree.current,400)

    def test_bet_uses_user_confirmed_fixed_fifty_without_amount_text(self):
        tree=M.GreedCardsPlay()
        r=report('押注并开始游戏');r.frame['high_low_template_state']='bet'
        decision=tree.decide(r)
        self.assertEqual(decision['kind'],'bet')
        self.assertEqual(tree.fees,0)
        tree.committed(decision)
        tree.decide(HOLD,cards())
        self.assertEqual(tree.fees,50)
        self.assertEqual(tree.rounds,1)

    def test_cursor_mismatch_prevents_click_and_releases_inputs(self):
        class MisplacedComputer(Computer):
            backend=object()
            def perform(self,action):
                return SkillResult(Outcome.SUCCESS,{'x':0,'y':0})
        computer=MisplacedComputer()
        result=M.GreedCardsPlay().run(lambda:{'report':BET},computer)
        self.assertEqual(result['outcome'],'unknown')
        self.assertIn('鼠标实际落点偏离',result['message'])
        self.assertFalse(any(a.name=='click' for a in computer.actions))
        self.assertEqual(computer.releases,1)

    def test_bet_click_uses_enclosed_button_not_explanation(self):
        from modular_agent.perception import GeneralVision
        from modular_agent.perception.screen import load_image
        observer=M.PlayObserver(ROOT,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,HISTORICAL_PROFILE)
        image=load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/bet_button_20261006.png')
        with patch.object(observer,'_ocr',side_effect=AssertionError('bet button must match')):
            result=observer.analyze(image,(332,177))
        decision=M.GreedCardsPlay().decide(result['report'])
        b=decision['target']
        self.assertEqual((b['x']+b['width']//2,b['y']+b['height']//2),(937,763))
        self.assertLess(b['y']+b['height'],810)
        image[550:620,470:740]=image[540,470]
        report=observer.vision.analyze(image,enable_ocr=False,enable_uia=False,enable_cv_buttons=False,enable_knowledge=False)
        observer._templates(image,(0,0),report)
        self.assertIsNone(M.label(report,'押注并开始游戏'))

    def test_batch_hold_plans_from_one_frame_and_checks_once_without_reclick(self):
        tree=M.GreedCardsPlay();tree.round_active=True
        computer=Computer();observations=iter([cards(),cards(held=(0,)),cards(held=(0,2))])
        def observe():
            try: hand=next(observations)
            except StopIteration:
                computer.stopped=True
                return {'report':HOLD,'cards':cards(held=(0,2))}
            return {'report':HOLD,'cards':hand}
        tree.run(observe,computer)
        clicks=[a for a in computer.actions if a.name=='click']
        self.assertEqual(len(clicks),3)  # Two holds followed by one replace.
        self.assertEqual([a.arguments['x'] for a in clicks[:2]],[200,640])
        self.assertTrue(all(a.arguments['duration']==.1 for a in computer.actions if a.name=='wait'))
        self.assertEqual(tree.pending['kind'],'replace')

    def test_hold_fast_path_uses_fresh_boxes_and_skips_rank_matching(self):
        import numpy as np
        from modular_agent.perception import GeneralVision
        from modular_agent.perception.screen import load_image
        observer=M.PlayObserver(ROOT,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,HISTORICAL_PROFILE)
        tree=M.GreedCardsPlay();tree.round_active=True;observer.context=tree
        image=load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/hold_unselected.png')
        initial=observer.analyze(image)
        tree.decide(initial['report'],initial['cards'])
        tree.pending={'kind':'hold_batch','state':'hold'}
        with patch.object(observer.cards,'read',side_effect=AssertionError('unchanged corners should skip ranks')):
            result=observer.analyze(image,(-400,20))
        self.assertTrue(result['report'].frame['hold_marker_fast_path'])
        self.assertEqual(len(result['report'].frame['template_diagnostics']),1)
        self.assertEqual(result['cards'][0]['bounds']['x'],initial['cards'][0]['bounds']['x']-400)
        observer._hand_masks=[np.zeros((64,64),np.uint8) for _ in range(5)]
        with patch.object(observer.cards,'read',wraps=observer.cards.read) as full:
            result=observer.analyze(image)
        self.assertEqual(full.call_count,1)
        self.assertFalse(result['report'].frame.get('hold_marker_fast_path',False))

    def test_fixed_size_observer_defaults_to_original_template_size(self):
        from modular_agent.perception import GeneralVision
        from modular_agent.perception.screen import load_image
        observer=M.PlayObserver(ROOT,GeneralVision(enable_uia=False,enable_cv_buttons=False),None,{})
        self.assertEqual(observer.template_scales,(1.0,))
        image=load_image(ROOT/'domains/hololive_dreams/data/high_low_samples/bet_button_20261006.png')
        with patch.object(observer,'_ocr',side_effect=AssertionError('new bet template matches original size')):
            result=observer.analyze(image)
        self.assertEqual(M.classify(result['report']),'bet')
        self.assertEqual(result['report'].frame['template_diagnostics']['hl_button_bet']['scale'],1)

if __name__=='__main__':unittest.main()
