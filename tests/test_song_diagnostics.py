import unittest,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from modular_agent.domains.hololive_dreams.song_diagnostics import SongDiagnostics
from modular_agent.domains.hololive_dreams.multi_live import StartGateCapture

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.events=[];self.progress=[]
        self.d=SongDiagnostics(clock=lambda:self.now,emit=lambda e,**k:self.events.append((e,k)),progress=self.progress.append)
        self.capture=Mock();self.capture.stats={'backend':'fake'};self.capture.bounds.return_value=(0,0,32,18)
        self.capture.grab.return_value=(None,(0,0,32,18))
        self.vision=Mock();self.vision.detect.return_value=SimpleNamespace(state='unknown',targets={});self.vision.gameplay_hud.return_value=False
        self.g=StartGateCapture(self.capture,self.vision,clock=lambda:self.now,diagnostic=self.d)
    def grab(self):self.now+=.04;return self.g.grab((0,0,1,1))
    def test_empty_frames_are_distinct_from_failed_hud(self):
        self.grab();self.assertEqual(self.d.snapshot()['empty_frames'],1)
        self.assertEqual(self.d.snapshot()['captured_frames'],0);self.vision.detect.assert_not_called()
        self.capture.grab.return_value=(np.zeros((18,32,3),np.uint8),(0,0,32,18));self.grab()
        self.assertEqual(self.d.snapshot()['captured_frames'],1);self.assertFalse(self.d.snapshot()['hud'])
    def test_hud_gate_and_processed_frames_separate(self):
        image=np.zeros((18,32,3),np.uint8);self.capture.grab.return_value=(image,(0,0,32,18));self.vision.gameplay_hud.return_value=True
        self.assertIsNone(self.grab()[0]);self.assertIs(self.grab()[0],image)
        self.assertTrue(self.d.snapshot()['gate_ready']);self.assertEqual(self.d.processed,0)
        self.d.frame(image,0,None,[],[],{'inhibited':'stale'},[])
        self.assertEqual(self.d.processed,1);self.assertEqual(self.d.inhibited,'stale')
    def test_heartbeat_is_rate_limited(self):
        for _ in range(50):self.d.check()
        self.assertEqual(len(self.progress),1)
        self.now=2;self.d.check();self.assertEqual(len(self.progress),2)
    def test_input_failure_counts_and_log_budget(self):
        for _ in range(100):self.d.input_edge({'success':False,'key':'s','down':True})
        self.assertEqual(self.d.failed_edges,100);self.assertEqual(len(self.events),12)
    def test_screenshots_bounded_and_summary_on_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            self.d.directory=Path(folder);image=np.zeros((18,32,3),np.uint8)
            for n in range(10):self.now=n*10.;self.d.image(image)
            self.assertEqual(len(list(Path(folder).glob('gate-*.jpg'))),4)
            self.d.finish({'reason':'cancelled'})
            self.assertEqual(json.loads((Path(folder)/'summary.json').read_text())['result']['reason'],'cancelled')
    def test_diagnostic_sink_failure_does_not_block_gate(self):
        self.d.emit=Mock(side_effect=OSError('disk full'));self.d.check()
        self.assertTrue(self.d.errors)
        self.capture.grab.return_value=(np.zeros((18,32,3),np.uint8),(0,0,32,18));self.vision.gameplay_hud.return_value=True
        self.grab();self.assertIsNotNone(self.grab()[0])
