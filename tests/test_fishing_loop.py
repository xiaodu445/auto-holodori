import unittest
from pathlib import Path
from types import SimpleNamespace
from modular_agent.realtime.fishing_loop import load_tree,LoopObserver
from modular_agent.computer import ActionComputer
from test_computer import FakeBackend
ROOT=Path(__file__).resolve().parents[1]
Tree=load_tree(ROOT)
BOUNDS=(0,0,1000,600)
BUTTON=dict(state='continue',point=(850,550),bounds=BOUNDS)

class FishingLoopTests(unittest.TestCase):
    def run_tree(self, observations, *, phase='control', live=True, max_rounds=2, realtime_reason='track_lost_result_pending', cancelled=lambda:False):
        clock=[0]; obs=iter(observations); calls=[]; clicks=[]; backend=FakeBackend()
        def observe(): return next(obs,{'state':'unknown','bounds':BOUNDS})
        def realtime(phase,remaining):
            calls.append(phase)
            return dict(reason=realtime_reason,outcome='unknown',verified=False)
        def sleep(dt): clock[0]+=dt
        with ActionComputer(live=True,backend=backend) as c:
            r=Tree(max_rounds=max_rounds,timeout=3,settlement_timeout=.3,transition_timeout=.3,poll_interval=.05,unknown_recovery=False).run(
                observe,realtime,lambda o:clicks.append(o),c,phase=phase,live=live,
                clock=lambda:clock[0],sleep=sleep,should_yield=cancelled)
        return r,calls,clicks
    def test_two_round_chain(self):
        r,calls,clicks=self.run_tree([BUTTON,BUTTON,BUTTON,{'state':'unknown'}, {'state':'bite'},BUTTON,BUTTON,{'state':'bite'}])
        self.assertEqual(calls,['control','waiting']); self.assertEqual(len(clicks),1)
        self.assertEqual(r['reason'],'round_limit'); self.assertEqual(r['confirmed_transitions'],1)
        self.assertEqual(r['outcome'],'unknown'); self.assertFalse(r['verified'])
    def test_visible_continue_retries_without_entering_waiting(self):
        clock=[0.0]; clicks=[]; calls=[]
        with ActionComputer() as c:
            r=Tree(timeout=5,poll_interval=.05,unknown_recovery=False).run(
                lambda:BUTTON,lambda phase,remaining:calls.append(phase) or {'reason':'track_lost_result_pending'},
                lambda o:clicks.append((clock[0],o)),c,phase='control',live=True,
                clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        self.assertGreaterEqual(len(clicks),2)
        self.assertLessEqual(len(clicks),5)
        self.assertTrue(all(b[0]-a[0]>=1 for a,b in zip(clicks,clicks[1:])))
        self.assertEqual(calls,['control'])
        self.assertEqual(r['confirmed_transitions'],0)
        self.assertEqual(r['reason'],'timeout')
    def test_second_click_succeeds_and_stops_retrying(self):
        clock=[0.0]; clicks=[]; calls=[]
        def observe(): return BUTTON if len(clicks)<2 else {'state':'bite','bounds':BOUNDS}
        def realtime(phase,remaining):
            calls.append(phase)
            return {'reason':'track_lost_result_pending' if len(calls)==1 else 'cancelled'}
        with ActionComputer() as c:
            r=Tree(timeout=5,poll_interval=.05,unknown_recovery=False).run(
                observe,realtime,lambda o:clicks.append(o),c,phase='control',live=True,
                clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        self.assertEqual(len(clicks),2)
        self.assertEqual(calls,['control','waiting'])
        self.assertEqual(r['confirmed_transitions'],1)
    def test_cancel_during_retry_wait_does_not_click_again(self):
        clock=[0.0]; clicks=[]
        with ActionComputer() as c:
            r=Tree(timeout=5,poll_interval=.05,unknown_recovery=False).run(
                lambda:BUTTON,lambda p,t:{'reason':'track_lost_result_pending'},clicks.append,c,
                phase='control',live=True,should_yield=lambda:clock[0]>=.5,
                clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        self.assertEqual(len(clicks),1); self.assertEqual(r['reason'],'cancelled')
    def test_unrecognized_settlement_does_not_click(self):
        r,calls,clicks=self.run_tree([])
        self.assertEqual(clicks,[]); self.assertEqual(r['reason'],'settlement_unknown')
    def test_changed_button_before_click_aborts(self):
        r,calls,clicks=self.run_tree([BUTTON,BUTTON,{**BUTTON,'point':(950,550)}])
        self.assertEqual(clicks,[]); self.assertEqual(r['reason'],'settlement_unknown')
    def test_realtime_error_not_restarted(self):
        r,calls,clicks=self.run_tree([BUTTON],realtime_reason='exception: unfocused')
        self.assertEqual(len(calls),1); self.assertEqual(clicks,[])
    def test_dry_run_and_cancel_do_not_click(self):
        r,calls,clicks=self.run_tree([BUTTON,BUTTON,BUTTON],phase='auto',live=False)
        self.assertEqual(r['reason'],'would_click_continue'); self.assertEqual(calls,[]); self.assertEqual(clicks,[])
        r,calls,clicks=self.run_tree([],cancelled=lambda:True)
        self.assertEqual(r['reason'],'cancelled'); self.assertEqual(calls,[])
    def test_initial_unknown_not_called(self):
        r,calls,clicks=self.run_tree([],phase='auto')
        self.assertEqual(r['reason'],'initial_state_unknown'); self.assertEqual(calls,[])
    def test_fresh_local_ocr_position_and_ambiguity(self):
        text=dict(text='继 续',confidence=.95,bounds=dict(x=820,y=520,width=60,height=30))
        roi=[.6,.65,1,1]
        report=SimpleNamespace(texts=[text])
        r=LoopObserver.classify(report,BOUNDS,roi)
        self.assertEqual(r['point'],(850,535))
        report.texts=[text,text]; self.assertEqual(LoopObserver.classify(report,BOUNDS,roi)['state'],'unknown')
        report.texts=[{**text,'bounds':dict(x=20,y=20,width=60,height=30)}]
        self.assertEqual(LoopObserver.classify(report,BOUNDS,roi)['state'],'unknown')
    def test_continue_click_no_alt_and_focus_guard(self):
        observer=object.__new__(LoopObserver)
        observer.capture=SimpleNamespace(bounds=lambda:BOUNDS)
        b=FakeBackend()
        with ActionComputer(live=True,backend=b) as c:
            observer.click(BUTTON,c)
            self.assertNotIn(('key','alt',True),b.events)
            self.assertIn(('position',850,550),b.events)
            observer.capture=SimpleNamespace(bounds=lambda:(10,0,1000,600))
            with self.assertRaises(RuntimeError): observer.click(BUTTON,c)
    def test_reward_continue_is_detected_in_normal_observer_without_ocr(self):
        from modular_agent.perception.screen import load_image
        image=load_image(ROOT/'domains/hololive_dreams/data/fishing_samples/reward-continue.png')[45:]
        h,w=image.shape[:2]; bounds=(500,300,w,h)
        observer=object.__new__(LoopObserver)
        observer.initial_bounds=bounds; observer.config={'control_roi':[0,0,.1,.1],'bite_roi':[0,0,.1,.1]}
        observer.detector=SimpleNamespace(control=lambda im:{'valid':False},bite=lambda im:{'bite':False})
        observer.capture=SimpleNamespace(bounds=lambda:bounds,grab=lambda roi:(image,bounds))
        observer.vision=None
        result=observer()
        self.assertEqual(result['state'],'continue')
        self.assertAlmostEqual(result['point'][0],1588,delta=4)
        self.assertAlmostEqual(result['point'][1],937,delta=4)
        self.assertIsNone(observer.vision)
    def test_click_uses_long_press_and_releases_on_failed_hold(self):
        from unittest.mock import patch
        observer=object.__new__(LoopObserver)
        observer.capture=SimpleNamespace(bounds=lambda:BOUNDS)
        b=FakeBackend()
        with ActionComputer(live=True,backend=b) as c:
            with patch.object(c,'_wait') as wait:
                observer.click(BUTTON,c)
                self.assertEqual([call.args[0] for call in wait.call_args_list],[.08,.12])
            self.assertFalse(c.buttons)
            with patch.object(c,'_wait',side_effect=[None,RuntimeError('cancel during hold')]):
                with self.assertRaises(RuntimeError): observer.click(BUTTON,c)
            self.assertFalse(c.buttons)
        self.assertEqual([event for event in b.events if event[0]=='button'],[
            ('button','left',True),('button','left',False),('button','left',True),('button','left',False)])
    def test_top_level_handoff_and_unknown_rejection(self):
        import tempfile
        from unittest.mock import patch,MagicMock
        from modular_agent.agent.general import GeneralAgent
        from test_connected_agent import Computer,Model,PROFILE,GAME,screen
        with tempfile.TemporaryDirectory() as root:
            agent=GeneralAgent(root,Computer(),Model([]),domain='hololive_dreams')
            agent.profiles=[PROFILE]
            report=screen(); report.windows=[GAME]
            decision={'skill':'fishing_loop','domain':'hololive_dreams'}
            observer=MagicMock(); observer.return_value={'state':'unknown'}
            with patch.object(agent,'_observe',return_value=report),patch('modular_agent.realtime.fishing_loop.LoopObserver',return_value=observer),patch('modular_agent.realtime.fishing_loop.run_fishing_loop') as run:
                with self.assertRaises(ValueError): agent._skill(decision,'循环钓鱼',lambda text:None)
                run.assert_not_called(); observer.close.assert_called_once()
            observer=MagicMock(); observer.return_value={'state':'control'}
            with patch.object(agent,'_observe',return_value=report) as observe,patch('modular_agent.realtime.fishing_loop.LoopObserver',return_value=observer),patch('modular_agent.realtime.fishing_loop.run_fishing_loop',return_value={'outcome':'unknown','reason':'round_limit'}) as run:
                r=agent._skill(decision,'循环钓鱼',lambda text:None)
                self.assertEqual(r['reason'],'round_limit')
                observe.assert_called_once_with('hololive_dreams',unittest.mock.ANY,'full')
                run.assert_called_once(); self.assertTrue(run.call_args.kwargs['live'])
                with self.assertRaises(ValueError): agent._skill(decision,'循环钓鱼',lambda text:None)
            self.assertTrue(any(x['skill']=='fishing_loop' for x in agent._skill_index('hololive_dreams')))
    def test_tree_exception_releases_existing_input(self):
        b=FakeBackend()
        with ActionComputer(live=True,backend=b) as c:
            from modular_agent.core import Action
            c.perform(Action('mouse_down',arguments={'button':'left'}))
            def observe(): raise RuntimeError('focus lost')
            r=Tree().run(observe,lambda p,r:None,lambda o:None,c,phase='auto',live=True)
            self.assertFalse(c.buttons); self.assertIn('focus lost',r['reason'])
    def test_recovery_closes_popup_then_resumes(self):
        clock=[0]; clicks=[]; seq=iter([{'state':'unknown','bounds':BOUNDS}])
        close=dict(state='close',point=(900,100),bounds=BOUNDS)
        recovery=iter([close,close,{'state':'control','bounds':BOUNDS}])
        with ActionComputer() as c:
            r=Tree(max_rounds=1,poll_interval=.01,settlement_timeout=.02).run(
                lambda:next(seq,{'state':'unknown','bounds':BOUNDS}),
                lambda phase,remaining:{'reason':'track_lost_result_pending'},lambda o:None,c,
                phase='auto',live=True,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt),
                observe_recovery=lambda:next(recovery,{'state':'unknown','bounds':BOUNDS}),click_recovery=clicks.append)
        self.assertEqual(clicks,[close]); self.assertEqual(len(r['rounds']),1)
        self.assertEqual(r['reason'],'round_limit')
    def test_recovery_center_once_and_dry_run_never_clicks(self):
        for live in (False,True):
            clock=[0]; clicks=[]
            unknown={'state':'unknown','bounds':BOUNDS}
            with ActionComputer() as c:
                r=Tree(poll_interval=.01).run(lambda:unknown,lambda p,r:None,clicks.append,c,
                     phase='auto',live=live,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
            self.assertEqual(len(clicks),10 if live else 0)
            self.assertEqual(r['recovery_actions'][0]['point'],(880,528))
            self.assertEqual(r['reason'],'initial_state_unknown')
    def test_close_detection_priority_and_scope(self):
        close=dict(text='×',confidence=.95,bounds=dict(x=900,y=100,width=20,height=20))
        cont=dict(text='继续',confidence=.95,bounds=dict(x=800,y=520,width=60,height=30))
        self.assertEqual(LoopObserver.classify_recovery(SimpleNamespace(texts=[cont,close]),BOUNDS)['state'],'close')
        close['bounds']['x']=30
        self.assertEqual(LoopObserver.classify_recovery(SimpleNamespace(texts=[close]),BOUNDS)['state'],'unknown')
    def test_close_or_continue_same_target_allows_two_attempts(self):
        clock=[0]; clicks=[]
        target={'state':'continue','point':(850,550),'bounds':BOUNDS}
        with ActionComputer(live=True) as c:
            r=Tree(max_rounds=1,timeout=.2,recovery_attempts=5,center_attempts=5,action_attempts=5,recovery_wait=.01,poll_interval=.001).run(
                lambda: {'state':'unknown','bounds':BOUNDS}, lambda p,r:{'reason':'x'}, clicks.append, c,
                phase='auto',live=True,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt),
                observe_recovery=lambda:target)
        self.assertEqual(len(clicks),5)
        self.assertEqual(r['recovery_actions'][0]['action'],'continue')
    def test_bad_limits_rejected(self):
        for value in (0,-1,True):
            with self.assertRaises(ValueError): Tree(max_rounds=value)

if __name__=='__main__': unittest.main()











