import unittest
from unittest.mock import patch
from test_rhythm_session import m, ROOT, Backend, ActionComputer
import modular_agent.computer.controller as executor
from test_rhythm_live_review import FakeCapture,FakeComputer,FakeVision,FakeController

class UnlimitedTests(unittest.TestCase):
    def test_unlimited_watchdog_still_honours_emergency(self):
        for emergency in (False,True):
            b=Backend();b.emergency=emergency
            c=ActionComputer(live=False,backend=b,hold_timeout=None);c.live=True;c.keys={'d'};c._held_since=0.
            with patch.object(c._closed,'wait',side_effect=[False,True]),patch.object(executor.time,'monotonic',return_value=100000.):c._watch()
            self.assertEqual(c.stopped,emergency)
            c.close();self.assertEqual(b.calls,[('d',False)])

    def test_unlimited_runtime_keeps_focus_failure_and_release(self):
        capture=FakeCapture();computer=FakeComputer()
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer) as factory,patch.object(m,'RhythmVision',FakeVision),patch.object(m,'RhythmController',FakeController):
            result=m.run(ROOT,123,live=True,overrides=dict(timeout=0,input_mode='all-held'))
        self.assertIsNone(factory.call_args.kwargs['hold_timeout'])
        self.assertIn('test_focus_lost',result['reason'])
        self.assertEqual(computer.calls,[('key_down','f'),('key_up','f')])
        self.assertTrue(capture.closed);self.assertTrue(computer.closed)

    def test_invalid_duration_rejected_before_capture(self):
        for duration in (-1,.5,float('inf'),float('nan')):
            with patch.object(m,'create_capture') as capture,self.assertRaises(ValueError):m.run(ROOT,123,overrides={'timeout':duration})
            capture.assert_not_called()

if __name__=='__main__':unittest.main()
