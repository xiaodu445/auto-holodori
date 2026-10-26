import unittest,importlib.util
from unittest.mock import Mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hotkey_gui',ROOT/'gui/release_gui.py')
gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)
class HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.app=gui.App.__new__(gui.App);self.app.hotkey_api=Mock();self.app.hotkey_api.GetAsyncKeyState.return_value=0x8000
        self.app.f8_down=False;self.app.process=None;self.app.closing=False;self.app.run=Mock();self.app._game_foreground=Mock(return_value=True)
    def test_rising_edge_once_not_repeat_on_hold(self):
        self.app.poll_hotkey();self.app.poll_hotkey();self.app.run.assert_called_once_with(single_song=True)
    def test_running_worker_never_restarts(self):
        self.app.process=Mock();self.app.poll_hotkey();self.app.process=None;self.app.poll_hotkey();self.app.run.assert_not_called()
    def test_other_application_foreground_no_start(self):
        self.app._game_foreground.return_value=False;self.app.poll_hotkey();self.app.run.assert_not_called()
    def test_closing_never_starts(self):
        self.app.closing=True;self.app.poll_hotkey();self.app.run.assert_not_called()
