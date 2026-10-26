"""Parameter parity and immediate engine initialization with a guarded baseline."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.rhythm_profile import load_profile
from modular_agent.domains.hololive_dreams.multi_live import StartGateCapture,run_song
from modular_agent.domains.hololive_dreams.multi_live_vision import LiveVision
from test_multi_live import Simulation

ROOT=Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_current_tuning_values_are_loaded_and_mechanism_off_retained(self):
        values,sources=load_profile(ROOT)
        self.assertEqual(values['input_mode'],'all-held');self.assertEqual(values['input_offset_ms'],75)
        self.assertEqual(values['release_lead_ms'],5);self.assertEqual(values['grid_snap_ms'],20)
        self.assertEqual(values['fps'],120);self.assertEqual(values['analysis_width'],960)
        self.assertEqual(values['mechanism_mode'],'off');self.assertEqual(values['global_flow'],'shadow')
        self.assertEqual(values['measure_clock'],'shadow');self.assertEqual(len(sources),2)
    def test_edits_to_tuning_are_read_without_executing_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            text=(ROOT/'run_rhythm_tuning.cmd').read_text(encoding='utf-8').replace('RHYTHM_OFFSET=75','RHYTHM_OFFSET=63')
            (root/'run_rhythm_tuning.cmd').write_text(text,encoding='utf-8')
            values,_=load_profile(root,'tuning');self.assertEqual(values['input_offset_ms'],63)
            self.assertNotIn('mechanism_mode',values)
    def test_bad_tuning_rejected_instead_of_silent_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'run_rhythm_tuning.cmd').write_text('set "RHYTHM_FPS=nan"',encoding='utf-8')
            with self.assertRaises(ValueError):load_profile(root,'tuning')
    def test_explicit_config_profile_does_not_add_cmd_values(self):
        self.assertEqual(load_profile(ROOT,'config'),({},[]))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.capture=Mock();self.capture.stats={};self.capture.bounds.return_value=(0,0,1260,709)
        self.capture.grab.return_value=(np.zeros((709,1260,3),np.uint8),(0,0,1260,709))
        self.vision=Mock();self.vision.detect.return_value=SimpleNamespace(state='loading',targets={})
        self.gate=StartGateCapture(self.capture,self.vision,clock=lambda:self.now)
    def grab(self):
        self.now+=.04;return self.gate.grab([0,0,1,1])[0]
    def test_loading_never_delivers_image_to_scheduler(self):
        for _ in range(10):self.assertIsNone(self.grab())
        self.assertFalse(self.gate.ready);self.vision.gameplay_hud.assert_not_called()
    def test_blank_fade_does_not_unlock(self):
        self.vision.detect.return_value=SimpleNamespace(state='unknown',targets={})
        self.vision.gameplay_hud.return_value=False
        for _ in range(10):self.assertIsNone(self.grab())
    def test_two_hud_frames_unlock_without_any_note_detection(self):
        self.vision.detect.return_value=SimpleNamespace(state='unknown',targets={})
        self.vision.gameplay_hud.return_value=True
        self.assertIsNone(self.grab());self.assertIsNotNone(self.grab());self.assertTrue(self.gate.ready)
    def test_dropped_settings_confirmation_yields_for_menu_retry(self):
        self.vision.detect.return_value=SimpleNamespace(state='settings',targets={'decide':{}})
        self.grab();self.now=2.1;self.assertIsNone(self.grab())
        self.assertEqual(self.gate.reason,'settings_not_accepted');self.assertFalse(self.gate.ready)
    def test_engine_starts_immediately_after_settings_click(self):
        game=Simulation();session=game.session();at=[];play=game.play
        def wrapped(**kwargs):
            at.append((game.states[game.index],kwargs));return play(**kwargs)
        session.play=wrapped;self.assertEqual(session.run()['outcome'],'success')
        self.assertEqual(at,[('loading',{'wait_for_start':True})])
    def test_real_hud_without_notes_and_no_menu_false_positives(self):
        vision=LiveVision(ROOT)
        raw=cv2.imread(str(ROOT/'domains/hololive_dreams/data/multi_live/rhythm_hud_reference.jpg'))
        image=cv2.resize(raw[:356,:632],(1260,709));image[105:635]=0
        self.assertTrue(vision.gameplay_hud(image))
        directory=ROOT/'domains/hololive_dreams/data/world_reference/20261021'
        for p in directory.glob('*.png'):
            client=cv2.imdecode(np.fromfile(p,dtype=np.uint8),1)[38:747,:1260]
            with self.subTest(path=p.name):self.assertFalse(vision.gameplay_hud(client))
    def test_existing_engine_all_six_keys_from_first_empty_play_frame(self):
        import time
        from test_rhythm_session import m
        from test_rhythm_live_review import FakeComputer,FakeVision
        class Capture:
            stats={'backend':'offline'};closed=False;n=0;last_timestamp=None
            def bounds(self):return (0,0,320,180)
            def grab(self,roi):
                self.n+=1;self.last_timestamp=time.perf_counter()
                return np.zeros((180,320,3),np.uint8),self.bounds()
            def close(self):self.closed=True
        capture=Capture();computer=FakeComputer();vision=Mock()
        vision.detect.return_value=SimpleNamespace(state='unknown',targets={})
        vision.gameplay_hud.return_value=True;vision.settlement.return_value=False
        original=m.create_capture
        values,_=load_profile(ROOT)
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision):
            result=run_song(ROOT,7,vision,engine=m,timeout=2,overrides=values,wait_for_start=True,
                            cancelled=lambda:capture.n>=5,progress=lambda _:None)
        self.assertEqual(result['reason'],'cancelled');self.assertTrue(result['scheduler_stopped'])
        self.assertEqual({key for action,key in computer.calls if action=='key_down'},set('sdfjkl'))
        self.assertEqual({key for action,key in computer.calls if action=='key_up'},set('sdfjkl'))
        self.assertTrue(capture.closed);self.assertTrue(computer.closed);self.assertIs(m.create_capture,original)


if __name__=='__main__':unittest.main()
