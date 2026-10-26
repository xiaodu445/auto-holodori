"""B025: launching from a terminal must activate the game before observation."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from modular_agent.core import Outcome

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('multi_live_focus_cli',ROOT/'tools/run_multi_live.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def window(foreground=False,minimized=False):
    return {'handle':7,'title':'hololive-Dreams','foreground':foreground,'minimized':minimized}


class StartupFocusTests(unittest.TestCase):
    def setUp(self):
        self.computer=Mock(live=True)
        self.computer.perform.return_value=SimpleNamespace(outcome=Outcome.SUCCESS)
        self.backend=Mock();self.wait=Mock();self.check=Mock();self.emit=Mock()
    def run_focus(self):
        cli.focus_game_on_start(self.backend,self.computer,7,wait=self.wait,check=self.check,emit=self.emit)
    def test_terminal_foreground_activates_then_waits_for_two_confirmations(self):
        self.backend.windows.side_effect=[[window()],[window()],[window(True)],[window(True)]]
        self.run_focus()
        action=self.computer.perform.call_args.args[0]
        self.assertEqual((action.name,action.arguments),('focus',{'handle':7}))
        self.assertEqual(self.wait.call_count,2)
        self.assertEqual(self.emit.call_args.args[0],'startup_focus_verified')
    def test_minimized_game_restored(self):
        self.backend.windows.side_effect=[[window(False,True)],[window(True)],[window(True)]]
        self.run_focus();self.computer.perform.assert_called_once()
    def test_already_foreground_no_focus_input(self):
        self.backend.windows.return_value=[window(True)]
        self.run_focus();self.computer.perform.assert_not_called()
    def test_activation_failure_is_bounded(self):
        self.backend.windows.return_value=[window()]
        self.computer.perform.return_value=SimpleNamespace(outcome=Outcome.FAILURE)
        with self.assertRaisesRegex(RuntimeError,'startup_focus_failed'):self.run_focus()
        self.assertEqual(self.computer.perform.call_count,3)
        self.assertEqual(self.wait.call_count,30)
    def test_disappeared_window_never_activates_another_handle(self):
        self.backend.windows.side_effect=[[window()],[]]
        with self.assertRaisesRegex(RuntimeError,'disappeared'):self.run_focus()
        self.computer.perform.assert_called_once()
    def test_cancel_during_activation_wait(self):
        self.backend.windows.return_value=[window()]
        self.wait.side_effect=RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):self.run_focus()
        self.computer.perform.assert_called_once()
    def test_plan_does_not_focus_or_run_session(self):
        with patch.object(cli,'focus_game_on_start') as focus,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--rounds','1']),0)
        focus.assert_not_called()
    def test_offline_image_does_not_focus(self):
        image=ROOT/'domains/hololive_dreams/data/world_reference/20261021/codex-clipboard-7fb66b8e-7561-4a23-bf2a-d0ef1255f1af.png'
        with patch.object(cli,'focus_game_on_start') as focus,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--rounds','1','--inspect-image',str(image)]),0)
        focus.assert_not_called()


if __name__=='__main__':unittest.main()
