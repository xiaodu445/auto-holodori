import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from modular_agent.agent.console_log import ConsoleLog

class ConsoleLogTests(unittest.TestCase):
    def test_output_saved_and_viewer_reopened(self):
        with tempfile.TemporaryDirectory() as folder:
            log = ConsoleLog(Path(folder))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                log.emit('步骤 1：读取屏幕', flush=True)
            self.assertIn('读取屏幕', output.getvalue())
            self.assertIn('步骤 1：读取屏幕', log.path.read_text(encoding='utf-8'))
            child = MagicMock()
            child.poll.return_value = None
            with patch('modular_agent.agent.console_log.subprocess.Popen', return_value=child) as spawn:
                log.show()
                log.show()
                self.assertEqual(spawn.call_count, 1)
                log.hide()
                child.terminate.assert_called_once()
                log.show()
                self.assertEqual(spawn.call_count, 2)
                log.close()
