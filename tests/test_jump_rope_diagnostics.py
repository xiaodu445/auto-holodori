import unittest
from types import SimpleNamespace
import numpy as np
from modular_agent.realtime.keyboard import run_key_loop

class DiagnosticSafetyTests(unittest.TestCase):
    def run_case(self, callback, cancelled=False):
        class Capture:
            closed=False
            def grab(self, roi): return np.zeros((12,12,3),dtype=np.uint8),(0,0,100,100)
            def bounds(self): return (0,0,100,100)
            def close(self): self.closed=True
        class Computer:
            live=False; keys=set(); buttons=set(); stopped=False; released=False
            def release_all(self): self.released=True
        class Controller:
            state='waiting_for_rope'; mode='rotation'; jumps=0; crossings=0
            def step(self,*args,**kwargs):
                return dict(down=False,stop='recognition_lost',missing_features=['avatar'])
        capture=Capture(); computer=Computer()
        def save(frames):
            self.assertTrue(capture.closed)
            self.assertTrue(computer.released)
            self.assertEqual(frames[0][0].shape,(12,12,3))
            callback(frames)
        result=run_key_loop(capture,SimpleNamespace(detect=lambda *a,**k: {}),Controller(),computer,
            dict(timeout=1,roi=[0,0,1,1],analysis_width=100,max_frame_age=1,fps=60),
            should_yield=lambda:cancelled,on_tracking_loss=save)
        return result
    def test_loss_saved_after_inputs_and_capture_released(self):
        saved=[]
        result=self.run_case(lambda frames:saved.extend(frames))
        self.assertEqual(len(saved),1)
        self.assertEqual(result['missing_features'],['avatar'])
        self.assertEqual(result['outcome'],'unknown')
    def test_diagnostic_failure_preserves_unknown_result(self):
        def fail(frames): raise OSError('disk unavailable')
        result=self.run_case(fail)
        self.assertEqual(result['diagnostic_error'],'disk unavailable')
        self.assertEqual(result['outcome'],'unknown')
    def test_manual_stop_does_not_save_loss(self):
        saved=[]
        result=self.run_case(lambda frames:saved.extend(frames),cancelled=True)
        self.assertEqual(saved,[])
        self.assertEqual(result['reason'],'cancelled')
