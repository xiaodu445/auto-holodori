import importlib.util,sys,unittest
from pathlib import Path
from unittest.mock import patch
from modular_agent.computer.controller import ActionComputer
import modular_agent.computer.controller as executor

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('session_test_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class Backend:
    emergency=False;fail_up=False
    def __init__(self):self.calls=[]
    def emergency_pressed(self):return self.emergency
    def key(self,key,down):
        if not down and self.fail_up:raise RuntimeError('test release failure')
        self.calls.append((key,down))

class SessionTests(unittest.TestCase):
    def test_default_thirty_second_guard_and_bounded_opt_in(self):
        for timeout,expired in ((30,True),(600,False)):
            backend=Backend();c=ActionComputer(live=False,backend=backend,hold_timeout=timeout)
            c.live=True;c.keys={'d'};c._held_since=0.
            with patch.object(c._closed,'wait',side_effect=[False,True]),patch.object(executor.time,'monotonic',return_value=31.):c._watch()
            self.assertEqual(c.stopped,expired)
            c.close();self.assertEqual(backend.calls,[('d',False)])
    def test_long_guard_still_expires_and_f12_still_stops(self):
        for elapsed,emergency in ((601.,False),(1.,True)):
            backend=Backend();backend.emergency=emergency
            c=ActionComputer(live=False,backend=backend,hold_timeout=600);c.live=True;c.keys={'d'};c._held_since=0.
            with patch.object(c._closed,'wait',return_value=False),patch.object(executor.time,'monotonic',return_value=elapsed):c._watch()
            self.assertTrue(c.stopped);self.assertFalse(c.keys);c.close()
    def test_stopped_session_cleanup_uses_release_all_not_perform(self):
        backend=Backend();computer=ActionComputer(live=False,backend=backend);computer.live=True;events=[]
        keys=m.KeyState(computer,True,['d'],events.append);keys.update({'d'});computer.stop()
        with patch.object(computer,'perform',side_effect=AssertionError('perform after stop forbidden')):keys.release()
        self.assertEqual(keys.down,set());self.assertEqual(backend.calls,[('d',True),('d',False)])
        self.assertTrue(events[-1]['cleanup_confirmation']);self.assertLessEqual(events[-1]['begin'],events[-1]['time']);computer.close()
    def test_release_failure_is_not_claimed_as_success(self):
        backend=Backend();computer=ActionComputer(live=False,backend=backend);computer.live=True
        keys=m.KeyState(computer,True,['d']);keys.update({'d'});computer._stop.set();backend.fail_up=True
        with self.assertRaises(RuntimeError):keys.release()
        self.assertEqual(keys.down,{'d'})
        backend.fail_up=False;keys.release();computer.close()
    def test_hold_timeout_validation(self):
        for invalid in (0,1801,float('nan'),True):
            with self.assertRaises(ValueError):ActionComputer(hold_timeout=invalid)
    def test_cleanup_failure_is_reported_without_thread_traceback(self):
        from test_rhythm_live_review import FakeCapture,FakeComputer
        computer=FakeComputer();capture=FakeCapture()
        def release_all():raise RuntimeError('test release failure')
        computer.release_all=release_all
        class Vision:
            hold_paths=[]
            def __init__(self,c):pass
            def detect(self,*args):
                if capture.n>=2:computer.stopped=True
                return []
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',Vision),patch.object(m.threading,'excepthook') as hook:
            result=m.run(ROOT,123,live=True,overrides={'input_mode':'all-held','fps':120,'timeout':1})
        self.assertIn('test release failure',result['cleanup_error']);hook.assert_not_called()
        self.assertTrue(computer.closed);self.assertTrue(capture.closed)

if __name__=='__main__':unittest.main()
