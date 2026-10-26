import unittest,threading
from unittest.mock import Mock
import numpy as np
from modular_agent.domains.hololive_dreams.recognition_preview import RecognitionPreview,render_recognition
from modular_agent.domains.hololive_dreams.song_diagnostics import SongDiagnostics
from modular_agent.domains.hololive_dreams.multi_live import StartGateCapture
from types import SimpleNamespace

class RecognitionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.display=Mock();self.display.stop=threading.Event()
        self.preview=RecognitionPreview({},factory=lambda *a,**k:self.display,clock=lambda:self.now)
        self.image=np.zeros((180,320,3),np.uint8)
    def test_latest_only_publish_rate_and_close(self):
        for _ in range(100):self.preview.publish(self.image,(0,0,320,180),{})
        self.assertEqual(self.display.publish.call_count,1)
        self.now=.11;self.preview.publish(self.image,(0,0,320,180),{})
        self.assertEqual(self.display.publish.call_count,2);self.preview.close();self.display.close.assert_called_once()
    def test_stopped_or_failed_view_does_not_stop_input_pipeline(self):
        self.display.stop.set();self.preview.publish(self.image,(),{});self.display.publish.assert_not_called()
        self.display.stop.clear();self.display.publish.side_effect=OSError('view failed')
        self.preview.publish(self.image,(),{});self.assertEqual(self.preview.error,'view failed')
    def test_render_notes_without_modifying_source(self):
        result=render_recognition(self.image,{'notes':[dict(center=(.5,.5),width=.1,height=.1)]},
            {'gate_ready':True,'gate_state':'unknown','keys':['s']},{},0)
        self.assertEqual(result.shape,(305,320,3));self.assertFalse(self.image.any());self.assertTrue(result[:180].any())
    def test_gate_waiting_frame_shown_without_unlock_or_input(self):
        capture=Mock();capture.stats={};capture.grab.return_value=(self.image,(0,0,320,180))
        vision=Mock();vision.detect.return_value=SimpleNamespace(state='loading',targets={})
        diagnostic=SongDiagnostics(preview=self.preview)
        gate=StartGateCapture(capture,vision,diagnostic=diagnostic)
        self.assertIsNone(gate.grab((0,0,1,1))[0]);self.assertFalse(gate.ready)
        self.assertEqual(self.display.publish.call_count,1);vision.gameplay_hud.assert_not_called()
    def test_processed_frame_publishes_actual_keys_and_notes(self):
        diagnostic=SongDiagnostics(preview=self.preview)
        diagnostic.frame(self.image,0,(0,0,320,180),[],[],{},['s','d'])
        args=self.display.publish.call_args.args
        self.assertEqual(args[2]['keys'],['s','d']);self.assertEqual(args[2]['processed_frames'],1)
