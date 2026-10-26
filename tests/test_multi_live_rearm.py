"""B027/B028 first-note key edges and exclusive Pickup selection."""
from pathlib import Path
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.multi_live import first_note_rearm_bindings,run_song
from modular_agent.domains.hololive_dreams.multi_live_vision import LiveVision,LiveFrame
from test_multi_live import Simulation,frame
from test_rhythm_session import m
from test_rhythm_live_review import FakeComputer,FakeVision

ROOT=Path(__file__).resolve().parents[1]
KEYS=set('sdfjkl')


class Controller:
    def __init__(self,config):self.c=config;self.keys=list('sdfjkl');self.block=set()
    def decide(self,notes,*args,**kwargs):return {'keys':set(self.keys),'events':[]}
    def guard_baseline_restore(self,decision,actual_down,now):
        decision['keys']-=self.block-set(actual_down)
        decision['restore_blocked']={key:[1] for key in self.block-set(actual_down)}
        return decision


class RearmTests(unittest.TestCase):
    def setUp(self):
        self.emit=Mock();self.computer=FakeComputer()
        bindings=first_note_rearm_bindings(SimpleNamespace(KeyState=m.KeyState,RhythmController=Controller),
                                           emit=self.emit,clock=lambda:0.)
        self.keys=bindings['KeyState'](self.computer,True,list('sdfjkl'))
        self.controller=bindings['RhythmController']({'release_gap_ms':8})
        self.keys.update(KEYS)
    def step(self,notes,now,inhibited=False):
        decision=self.controller.decide(notes)
        if inhibited:decision['inhibited']='stale frame >50ms';decision['keys']=set()
        self.controller.guard_baseline_restore(decision,self.keys.down,now)
        self.keys.update(decision['keys']);return decision
    def test_first_note_releases_then_represses_after_gap_only_once(self):
        self.step([],9.);self.assertEqual(len(self.computer.calls),6)
        self.step([object()],10.)
        self.assertEqual(len(self.computer.calls),12);self.assertFalse(self.keys.down)
        self.step([object()],10.004);self.assertEqual(len(self.computer.calls),12)
        self.step([object()],10.009);self.assertEqual(self.keys.down,KEYS)
        self.assertEqual(len(self.computer.calls),18)
        self.step([object()],11.);self.assertEqual(len(self.computer.calls),18)
    def test_no_note_no_rearm(self):
        for n in range(30):self.step([],float(n))
        self.assertEqual(len(self.computer.calls),6);self.emit.assert_not_called()
    def test_stale_first_note_does_not_trigger(self):
        self.step([object()],10.,inhibited=True)
        self.assertFalse(any(c.args[0]=='first_note_baseline_release' for c in self.emit.call_args_list))
        self.step([],10.1);self.step([object()],11.)
        self.assertEqual(self.emit.call_args_list[0].args[0],'first_note_baseline_release')
    def test_original_restore_guard_still_blocks_unsafe_key(self):
        self.controller.block={'j'};self.step([object()],10.);decision=self.step([],10.009)
        self.assertNotIn('j',self.keys.down);self.assertEqual(set(decision['restore_blocked']),{'j'})
    def test_release_failure_cannot_repress(self):
        self.computer.fail_key='f'
        with self.assertRaises(RuntimeError):self.step([object()],10.)
        self.assertEqual(sum(a=='key_down' for a,k in self.computer.calls),6)
    def test_bindings_are_per_song(self):
        self.step([object()],10.);self.step([],10.009)
        second=first_note_rearm_bindings(SimpleNamespace(KeyState=m.KeyState,RhythmController=Controller),clock=lambda:0.)
        keys=second['KeyState'](self.computer,True,list('sdfjkl'));keys.update(KEYS)
        controller=second['RhythmController']({'release_gap_ms':8})
        decision=controller.decide([object()]);controller.guard_baseline_restore(decision,keys.down,20.)
        self.assertFalse(keys.down)


class PickupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.vision=LiveVision(ROOT)
    def image(self):
        path=ROOT/'domains/hololive_dreams/data/world_reference/20261021/codex-clipboard-ae214b27-1e43-42e5-b338-25ffe9fc89c4.png'
        return cv2.imdecode(np.fromfile(path,dtype=np.uint8),1)[38:747,:1260]
    def test_check_icon_present_or_absent_always_pickup(self):
        for erase in (False,True):
            image=self.image()
            if erase:image[614:641,875:907]=0
            f=self.vision.detect(image)
            self.assertEqual(f.state,'song');self.assertEqual(set(f.targets),{'pickup'})
    def test_decide_cannot_be_song_fallback(self):
        game=Simulation();session=game.session(step_timeout=3);session.click=Mock()
        session.observe=lambda **k:LiveFrame('song',{'decide':{'enabled':True,'label':'song_decide'}})
        self.assertEqual(session.run()['outcome'],'unknown');session.click.assert_not_called()
    def test_lost_pickup_retries_pickup_then_decide_only_at_settings(self):
        game=Simulation(drop=True);self.assertEqual(game.session(2).run()['outcome'],'success')
        songs=[label for state,label,_ in game.calls if state=='song']
        self.assertTrue(songs);self.assertEqual(set(songs),{'pickup'})
        self.assertEqual({label for state,label,_ in game.calls if state=='settings'},{'decide'})
    def test_missing_or_disabled_pickup_never_uses_decide(self):
        image=self.image();image[600:650,905:1010]//=2
        f=self.vision.detect(image);self.assertNotIn('decide',f.targets);self.assertNotIn('pickup',f.targets)
    def test_pickup_does_not_require_manual_decide_visible(self):
        image=self.image();image[590:680,1030:1240]=0
        f=self.vision.detect(image)
        self.assertEqual(f.state,'song');self.assertEqual(set(f.targets),{'pickup'})
    def test_pickup_disabled_flicker_cannot_reset_three_attempt_budget(self):
        game=Simulation();session=game.session(step_timeout=4);clicks=[]
        def observe(**kwargs):
            # Multiple stable enabled/disabled phases used to create new episodes.
            enabled=int(game.now/1.2)%2==0
            return LiveFrame('song',{'pickup':{'label':'pickup','enabled':True,'bounds':{'x':10,'y':10,'width':20,'height':20}}} if enabled else {})
        session.observe=observe;session.click=lambda t:clicks.append(t['label']);session.timeout=15
        session.run();self.assertEqual(clicks,['pickup']*3)


class RealEngineRearmTests(unittest.TestCase):
    def test_first_note_down_up_down_and_cleanup_with_existing_engine(self):
        class Capture:
            stats={'backend':'offline'};closed=False;n=0;last_timestamp=None
            def bounds(self):return (0,0,320,180)
            def grab(self,roi):
                self.n+=1;self.last_timestamp=time.perf_counter()
                return np.zeros((180,320,3),np.uint8),self.bounds()
            def close(self):self.closed=True
        capture=Capture();computer=FakeComputer();vision=Mock();events=[]
        vision.detect.return_value=SimpleNamespace(state='unknown',targets={})
        vision.gameplay_hud.return_value=True;vision.settlement.return_value=False
        class Notes(FakeVision):
            def detect(self,image,stamp):
                return [m.Note(lane=2,kind='tap',center=(.5,.12),width=.1,height=.025,confidence=1.,color='blue')] if capture.n>=4 else []
        original=m.KeyState;original_controller=m.RhythmController
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',Notes):
            result=run_song(ROOT,7,vision,engine=m,timeout=2,wait_for_start=True,
                overrides={'input_mode':'all-held','release_gap_ms':8,'fps':120},
                cancelled=lambda:capture.n>=10,progress=lambda _:None,emit=lambda event,**kw:events.append((event,kw)))
        self.assertEqual(result['reason'],'cancelled');self.assertTrue(result['scheduler_stopped'])
        for key in KEYS:
            self.assertEqual([a for a,k in computer.calls if k==key],['key_down','key_up','key_down','key_up'])
        self.assertEqual([e for e,_ in events if e.startswith('first_note_')],['first_note_baseline_release','first_note_baseline_rearm_requested'])
        self.assertTrue(capture.closed);self.assertIs(m.KeyState,original);self.assertIs(m.RhythmController,original_controller)


if __name__=='__main__':unittest.main()
