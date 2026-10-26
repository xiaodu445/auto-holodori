import importlib.util,unittest,contextlib,io,json,tempfile
from unittest.mock import Mock
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_cli',ROOT/'tools/run_multi_live.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
class ReleaseOptionsTests(unittest.TestCase):
    def test_gui_stop_requests_cooperative_exit(self):
        spec=importlib.util.spec_from_file_location('release_gui_test',ROOT/'gui/release_gui.py')
        gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)
        app=gui.App.__new__(gui.App);app.process=Mock();app.status=Mock();app.stop=Mock()
        with tempfile.TemporaryDirectory() as folder:
            app.stop_file=Path(folder)/'cancel'
            app.cancel()
            self.assertTrue(app.stop_file.exists())
            app.process.terminate.assert_not_called();app.process.kill.assert_not_called()
    def test_close_waits_for_input_cleanup(self):
        spec=importlib.util.spec_from_file_location('release_gui_close_test',ROOT/'gui/release_gui.py')
        gui=importlib.util.module_from_spec(spec);spec.loader.exec_module(gui)
        app=gui.App.__new__(gui.App);app.process=Mock();app.root=Mock();app.cancel=Mock()
        app.close();app.cancel.assert_called_once();app.root.destroy.assert_not_called()
    def test_overrides_keep_profile(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):self.assertEqual(cli.main(['--rounds','2','--offset','80','--grid-snap','15']),0)
        data=json.loads(out.getvalue());config=data['rhythm_overrides']
        self.assertEqual(config['input_mode'],'all-held');self.assertEqual(config['mechanism_mode'],'off')
        self.assertEqual(config['input_offset_ms'],80);self.assertEqual(config['grid_snap_ms'],15)
    def test_bad_options_never_start(self):
        for option in [['--grid-snap','26'],['--offset','nan'],['--window-width','1280'],['--rounds','0']]:
            with self.subTest(option=option),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                cli.main(['--rounds','3',*option])
if __name__=='__main__':unittest.main()
