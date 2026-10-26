import contextlib,io,json,unittest
from test_multi_live import Simulation
from test_rhythm_release import cli
from modular_agent.domains.hololive_dreams.multi_live import MultiLiveSession

class SessionDurationTests(unittest.TestCase):
    def make_session(self,game,**options):
        return MultiLiveSession(rounds=999,observe=game.observe,click=game.click,play=game.play,wait=game.wait,clock=lambda:game.now,**options)
    def test_default_999_rounds_can_pass_two_hours(self):
        game=Simulation();original=game.play
        def play(**options):
            result=original(**options);game.now+=180;return result
        game.play=play
        result=self.make_session(game).run()
        self.assertEqual(result['outcome'],'success');self.assertEqual(result['completed_rounds'],999)
        self.assertGreater(game.now,7200);self.assertEqual(sum(s=='again' for s,_,_ in game.calls),998)
    def test_explicit_positive_total_timeout_still_works(self):
        game=Simulation();original=game.play
        def play(**options):
            result=original(**options);game.now+=180;return result
        game.play=play
        result=self.make_session(game,timeout=7200).run()
        self.assertEqual(result['reason'],'session_timeout');self.assertLess(result['completed_rounds'],999)
    def test_cancellation_after_two_hours_still_stops(self):
        game=Simulation();original=game.play
        def play(**options):
            result=original(**options);game.now+=180;return result
        game.play=play
        def check():
            if game.now>7200:raise RuntimeError('cancelled')
        result=self.make_session(game,check=check).run()
        self.assertEqual(result['reason'],'cancelled')
    def test_step_budget_retained_with_unlimited_total(self):
        game=Simulation();game.click=lambda target:None
        result=self.make_session(game,step_timeout=4).run()
        self.assertEqual(result['reason'],'state_timeout:world')
    def test_cli_defaults_and_explicit_zero(self):
        for arguments in ([],['--timeout','0']):
            out=io.StringIO()
            with contextlib.redirect_stdout(out):self.assertEqual(cli.main(['--rounds','999',*arguments]),0)
            self.assertEqual(json.loads(out.getvalue())['timeout'],0)
    def test_invalid_total_and_zero_song_or_matching_rejected(self):
        for arguments in (['--timeout','-1'],['--timeout','nan'],['--timeout','inf'],['--song-timeout','0'],['--matching-timeout','0']):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):cli.main(['--rounds','999',*arguments])
