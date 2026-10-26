import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modular_agent.realtime import jump_rope

ROOT=Path(__file__).resolve().parents[1]

class JumpRopeStartupTests(unittest.TestCase):
    def result(self, reason='timeout'):
        return dict(reason=reason,frames=5,actual_fps=58.5,outcome='unknown')

    def test_default_focuses_selected_window_and_remains_judgment_only(self):
        with patch('sys.argv',['jump_rope','--project-root',str(ROOT),'--window-handle','123','--start-delay','0']), patch('modular_agent.computer.windows.WindowsBackend') as backend, patch.object(jump_rope,'run_jump_rope',return_value=self.result()) as run:
            self.assertEqual(jump_rope.main(),0)
            backend.return_value.focus.assert_called_once_with(123)
            self.assertFalse(run.call_args.kwargs['live'])
            self.assertFalse(run.call_args.args[1].live)

    def test_no_focus_preserves_manual_option(self):
        with patch('sys.argv',['jump_rope','--project-root',str(ROOT),'--window-handle','123','--start-delay','0','--no-focus']), patch('modular_agent.computer.windows.WindowsBackend') as backend, patch.object(jump_rope,'run_jump_rope',return_value=self.result('exception: window_unavailable_or_unfocused')):
            self.assertEqual(jump_rope.main(),1)
            backend.assert_not_called()

    def test_startup_failure_logged_and_not_uncaught(self):
        with tempfile.TemporaryDirectory() as root,patch('sys.argv',['jump_rope','--project-root',root]),patch.object(jump_rope,'main',side_effect=RuntimeError('focus failed')):
            self.assertEqual(jump_rope.cli(),1)
            self.assertIn('focus failed',(Path(root)/'runtime/jump-rope/startup-error.log').read_text(encoding='utf-8'))

    def test_focus_failure_prevents_loop(self):
        with tempfile.TemporaryDirectory() as root,patch('sys.argv',['jump_rope','--project-root',root,'--window-handle','123','--start-delay','0']),patch.object(jump_rope,'load',return_value=({},None,None)),patch('modular_agent.computer.windows.WindowsBackend') as backend,patch.object(jump_rope,'run_jump_rope') as run:
            backend.return_value.focus.side_effect=RuntimeError('focus rejected')
            self.assertEqual(jump_rope.cli(),1)
            run.assert_not_called()

    def test_missing_calibration_rejects_live_before_desktop_access(self):
        with patch('sys.argv',['jump_rope','--project-root',str(ROOT),'--live']),patch('modular_agent.computer.windows.WindowsBackend') as backend:
            with self.assertRaises(SystemExit) as error:jump_rope.main()
            self.assertEqual(error.exception.code,2)
            backend.assert_not_called()

    def test_experimental_flag_enables_input_without_claiming_calibration(self):
        with patch('sys.argv',['jump_rope','--project-root',str(ROOT),'--experimental-live','--window-handle','123','--start-delay','0']),patch('modular_agent.computer.windows.WindowsBackend'),patch.object(jump_rope,'ActionComputer') as computer,patch.object(jump_rope,'run_jump_rope',return_value=self.result()) as run:
            computer.return_value.__enter__.return_value.stopped=False
            self.assertEqual(jump_rope.main(),0)
            self.assertTrue(run.call_args.kwargs['live'])
            self.assertTrue(run.call_args.kwargs['experimental'])
            self.assertFalse(jump_rope.load(ROOT)[0]['calibration']['verified'])

    def test_space_pulse_sends_explicit_edges_once(self):
        from types import SimpleNamespace
        from modular_agent.core import Outcome
        from modular_agent.realtime.keyboard import KeyLatch
        actions=[]
        def perform(action):
            actions.append(action)
            return SimpleNamespace(outcome=Outcome.SUCCESS)
        latch=KeyLatch(SimpleNamespace(perform=perform),True,'space')
        latch.set(True);latch.set(True);latch.set(False);latch.set(False)
        self.assertEqual([a.name for a in actions],['key_down','key_up'])
        self.assertTrue(all(a.arguments['key']=='space' for a in actions))

    def test_focus_reason_readable_and_launcher_keeps_window(self):
        text=jump_rope.format_result(self.result('exception: window_unavailable_or_unfocused'))
        self.assertIn('游戏失焦',text)
        launcher=(ROOT/'run_jump_rope.cmd').read_text(encoding='utf-8-sig')
        self.assertIn('pause',launcher)
        self.assertIn('exit /b %jump_rope_exit%',launcher)

if __name__=='__main__':unittest.main()
