"""Offline MULTI flow, delivery loss, ownership and archived UI regressions."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.multi_live import MultiLiveSession,SettlementMonitor,run_song
from modular_agent.domains.hololive_dreams.multi_live_vision import LiveFrame,LiveVision

ROOT=Path(__file__).resolve().parents[1]


def frame(state,key='',enabled=True):
    actions={'world':'stage','portal':'multi','grade':'grade','song':'pickup','settings':'decide',
             'result':'next','reward':'close','achievement':'close','popup':'close','again':'again'}
    action=actions.get(state)
    target={'label':action,'enabled':enabled,'bounds':{'x':10,'y':10,'width':20,'height':20}}
    return LiveFrame(state,{action:target} if action else {},key=key)


class Simulation:
    def __init__(self,rounds=1,drop=False):
        self.now=0.;self.index=0;self.calls=[];self.plays=0;self.attempts={};self.drop=drop;self.polls=0
        self.states=['world','portal','grade','matching','song','settings','loading','playing',
                     'result','reward','achievement','reward','result','result','again']
        self.result_keys={8:'score',12:'personal',13:'exp'}
    def observe(self,ocr=False):
        state=self.states[self.index];self.polls+=1
        if state in ('matching','loading') and self.polls>=4:
            self.index+=1;self.polls=0;state=self.states[self.index]
        return frame(state,self.result_keys.get(self.index,''))
    def click(self,target):
        state=self.states[self.index]
        assert state not in ('matching','loading','playing')
        self.calls.append((state,target['label'],self.now))
        key=(self.plays,self.index);self.attempts[key]=self.attempts.get(key,0)+1
        if self.drop and self.attempts[key]==1:return
        if state=='again':self.index=3
        else:self.index+=1
        self.polls=0
    def play(self,wait_for_start=False):
        if wait_for_start:
            if self.states[self.index]=='settings':
                self.wait(2)
                return {'reason':'settings_not_accepted','cleanup_error':None,'scheduler_stopped':True}
            assert self.states[self.index]=='loading'
            self.index+=1
        assert self.states[self.index]=='playing'
        self.plays+=1;self.index+=1;self.polls=0
        return {'reason':'settlement_observed','cleanup_error':None,'scheduler_stopped':True}
    def wait(self,seconds):self.now+=seconds
    def session(self,rounds=1,**kwargs):
        return MultiLiveSession(rounds=rounds,observe=self.observe,click=self.click,play=self.play,
                                wait=self.wait,clock=lambda:self.now,timeout=600,**kwargs)


class FlowTests(unittest.TestCase):
    def test_n_rounds_no_n_plus_one_and_rewards_not_counted(self):
        game=Simulation();result=game.session(3).run()
        self.assertEqual(result['outcome'],'success');self.assertEqual(game.plays,3)
        self.assertEqual(sum(s=='again' for s,_,_ in game.calls),2)
        self.assertEqual(result['completed_rounds'],3);self.assertFalse(result['rewards_verified'])
    def test_first_click_lost_each_stage_retried(self):
        game=Simulation(drop=True);result=game.session().run()
        self.assertEqual(result['outcome'],'success')
        portal=[t for s,_,t in game.calls if s=='portal']
        self.assertEqual(len(portal),2);self.assertGreaterEqual(portal[1]-portal[0],2)
    def test_unchanged_page_three_attempts_then_timeout(self):
        game=Simulation();game.observe=lambda **k:frame('portal');click=Mock()
        session=game.session(step_timeout=8);session.click=click
        self.assertEqual(session.run()['outcome'],'unknown');self.assertEqual(click.call_count,3)
    def test_disabled_control_zero_input(self):
        game=Simulation();game.observe=lambda **k:frame('portal',enabled=False);click=Mock()
        session=game.session(step_timeout=3);session.click=click
        self.assertEqual(session.run()['outcome'],'unknown');click.assert_not_called()
    def test_matching_button_never_clicked_even_when_enabled(self):
        game=Simulation();game.observe=lambda **k:LiveFrame('matching',{'decide':{'enabled':True,'label':'决定成员'}})
        session=game.session(matching_timeout=3);session.click=Mock()
        self.assertEqual(session.run()['outcome'],'unknown');session.click.assert_not_called()
    def test_cleanup_failure_stops_before_menu(self):
        game=Simulation();session=game.session();session.play=lambda **k:{'reason':'settlement_observed','scheduler_stopped':False}
        result=session.run();self.assertEqual(result['reason'],'rhythm_cleanup_unconfirmed')
        self.assertFalse(any(s=='result' for s,_,_ in game.calls));self.assertEqual(result['completed_rounds'],0)
    def test_song_without_settlement_does_not_count(self):
        game=Simulation();session=game.session();session.play=lambda **k:{'reason':'song_timeout','scheduler_stopped':True}
        result=session.run();self.assertEqual(result['completed_rounds'],0)
        self.assertFalse(any(s=='result' for s,_,_ in game.calls))
    def test_cancel_before_input(self):
        game=Simulation();session=game.session();session.check=Mock(side_effect=RuntimeError('cancelled'))
        self.assertEqual(session.run()['reason'],'cancelled');self.assertFalse(game.calls)
    def test_changed_unknown_calls_ocr_and_new_button(self):
        game=Simulation();events=[];stage=[0]
        def observe(ocr=False):
            if stage[0]==0:return frame('portal')
            if stage[0]==1:
                if ocr:events.append('ocr');return frame('popup','达成奖励')
                return frame('unknown')
            return frame('again')
        def click(t):events.append(t['label']);stage[0]+=1
        session=game.session(step_timeout=4);session.observe=observe;session.click=click;session.completed=1
        # Use result as first page so the completed budget does not authorize new entry.
        old=observe
        session.observe=lambda **k:frame('result','personal') if stage[0]==0 else old(**k)
        self.assertEqual(session.run()['outcome'],'success')
        self.assertEqual(events[0],'next');self.assertEqual(events[-1],'close')
        self.assertGreaterEqual(events.count('ocr'),2)
    def test_unexpected_play_cannot_take_input(self):
        game=Simulation();session=game.session();session.observe=lambda **k:frame('playing')
        self.assertEqual(session.run()['reason'],'unexpected_gameplay_without_confirmed_settings');self.assertEqual(game.plays,0)
    def test_ocr_only_world_is_reobserved_before_click(self):
        game=Simulation();clicks=[];done=[False]
        def observe(ocr=False):
            if done[0]:return frame('again')
            return frame('world') if ocr else frame('unknown')
        session=game.session(step_timeout=4);session.observe=observe
        session.click=lambda t:(clicks.append(t['label']),done.__setitem__(0,True))
        # Verify the first world navigation is sent; the synthetic continue page
        # cannot finish an unplayed target, so stop explicitly at that boundary.
        session.check=lambda:(_ for _ in ()).throw(RuntimeError('boundary')) if done[0] else None
        session.run();self.assertEqual(clicks,['stage'])


class MonitorTests(unittest.TestCase):
    def test_existing_engine_stops_scheduler_and_releases_before_return(self):
        import time
        from test_rhythm_session import m
        from test_rhythm_live_review import FakeComputer,FakeVision,FakeController
        class Capture:
            stats={'backend':'offline'};closed=False;last_timestamp=None
            def bounds(self):return (0,0,320,180)
            def grab(self,roi):
                self.last_timestamp=time.perf_counter()
                return np.zeros((180,320,3),np.uint8),self.bounds()
            def close(self):self.closed=True
        capture=Capture();computer=FakeComputer();vision=Mock();vision.settlement.return_value=True
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision),patch.object(m,'RhythmController',FakeController):
            result=run_song(ROOT,7,vision,engine=m,timeout=2,progress=lambda _:None)
        self.assertEqual(result['reason'],'settlement_observed');self.assertTrue(result['scheduler_stopped'])
        self.assertTrue(capture.closed);self.assertTrue(computer.closed)
        self.assertEqual(computer.calls,[('key_down','f'),('key_up','f')])
    def test_two_result_frames_and_gap_resets(self):
        vision=Mock();vision.settlement.side_effect=[True,False,True,True]
        monitor=SettlementMonitor(vision,clock=lambda:0)
        for stamp in (0.,.3,.6):monitor.frame(None,stamp,None)
        self.assertFalse(monitor.should_yield());monitor.frame(None,.9,None)
        self.assertTrue(monitor.should_yield());self.assertEqual(monitor.reason,'settlement_observed')
    def test_rest_is_not_song_end(self):
        vision=Mock();vision.settlement.return_value=False
        monitor=SettlementMonitor(vision,clock=lambda:0)
        for n in range(100):monitor.frame(None,n*.3,None)
        self.assertFalse(monitor.should_yield())
    def test_run_song_passes_callbacks_and_propagates_cleanup(self):
        engine=Mock();engine.run.return_value={'reason':'cancelled','cleanup_error':'key_up_failed'}
        result=run_song(ROOT,7,Mock(),engine=engine)
        self.assertEqual(result['reason'],'cleanup_failed')
        kwargs=engine.run.call_args.kwargs
        self.assertTrue(kwargs['live']);self.assertNotIn('overrides',kwargs)
        self.assertTrue(callable(kwargs['should_yield']))


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=LiveVision(ROOT)
    def image(self,prefix):
        path=next((ROOT/'domains/hololive_dreams/data/world_reference/20261021').glob('codex-clipboard-'+prefix+'*.png'))
        return cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)[38:747,:1260]
    def test_all_sixteen_reference_states(self):
        expected={'355deb':'portal','55bc73':'grade','bb7dc':'loading','b9bd9':'matching','ae214':'song','ed5df':'matching',
                  '296118':'settings','34d0e':'loading','7fb66':'result','2117f':'reward','9d0c8':'achievement',
                  '019012':'result','c5635':'result','b8916':'result','81b1a':'result','aadff':'again'}
        for prefix,state in expected.items():
            with self.subTest(prefix=prefix):self.assertEqual(self.vision.detect(self.image(prefix)).state,state)
    def test_song_check_glyph_still_selects_pickup_not_decide(self):
        f=self.vision.detect(self.image('ae214'))
        self.assertIn('pickup',f.targets);self.assertNotIn('decide',f.targets)
    def test_header_without_next_not_settlement(self):
        image=self.image('7fb66');image[605:690,1000:1250]=0
        self.assertFalse(self.vision.settlement(image))
    def test_loading_and_matching_are_not_settlement(self):
        for prefix in ('bb7dc','34d0e','b9bd9','ed5df','296118'):
            self.assertFalse(self.vision.settlement(self.image(prefix)))
    def test_scale_and_desktop_target_mapping(self):
        image=cv2.resize(self.image('7fb66'),(1008,567))
        f=self.vision.detect(image,(400,200,1008,567))
        self.assertEqual(f.state,'result');self.assertGreater(f.targets['next']['bounds']['x'],1200)
    def test_dynamic_score_and_actors_are_not_anchors(self):
        image=self.image('7fb66');image[150:565,:]=0;image[:55,800:1100]=0
        self.assertTrue(self.vision.settlement(image))
    def test_dark_disabled_next_is_not_clickable(self):
        image=self.image('7fb66');image[605:690,1000:1250]//=2
        self.assertNotIn('next',self.vision.detect(image).targets)
    def test_ocr_ok_on_registered_popup_with_current_colour(self):
        image=np.full((709,1260,3),70,np.uint8)
        cv2.rectangle(image,(500,360),(760,450),(255,180,25),-1)
        cv2.putText(image,'OK',(585,417),cv2.FONT_HERSHEY_SIMPLEX,1.5,(255,255,255),3)
        words=[{'id':'title','text':'达成奖励','confidence':.99,'bounds':{'x':550,'y':200,'width':150,'height':40},'source':'ocr'},
               {'id':'ok','text':'OK','confidence':.99,'bounds':{'x':583,'y':382,'width':72,'height':40},'source':'ocr'}]
        with patch.object(self.vision,'ocr',Mock(recognize=Mock(return_value=words))):
            result=self.vision.discover(image,(0,0,1260,709))
        self.assertIsNotNone(result);self.assertEqual(result.state,'popup');self.assertIn('close',result.targets)
    def test_ocr_member_confirmation_always_waits(self):
        words=[{'text':'决定成员','confidence':1.,'bounds':{'x':1000,'y':600,'width':100,'height':40}}]
        with patch.object(self.vision,'ocr',Mock(recognize=Mock(return_value=words))):
            result=self.vision.discover(np.zeros((709,1260,3),np.uint8),(0,0,1260,709))
        self.assertEqual(result.state,'matching');self.assertFalse(result.targets)


if __name__=='__main__':unittest.main()
