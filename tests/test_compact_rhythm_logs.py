import unittest,tempfile,json,os,time,stat
from pathlib import Path
from unittest.mock import patch,Mock
from modular_agent.domains.hololive_dreams.rhythm_journal import RhythmJournal,cleanup_old_rhythm_logs,compact_result
from modular_agent.domains.hololive_dreams.song_diagnostics import SongDiagnostics

class CompactLoggingTests(unittest.TestCase):
    def test_other_task_journal_behavior_unchanged(self):
        from modular_agent.domains.hololive_dreams.daily_journal import DailyJournal
        with tempfile.TemporaryDirectory() as folder:
            journal=DailyJournal(folder)
            for n in range(3):journal('rhythm_diagnostic',rows=[n])
            rows=[json.loads(line) for line in (journal.directory/'events.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),3);self.assertEqual(rows[-1]['rows'],[2])
    def test_rotated_marked_rhythm_directory_can_expire(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'20260101-000000-abcdef12';p.mkdir()
            (p/'events.jsonl').write_text('{"event":"result"}')
            (p/'rhythm-log-policy.json').write_text('{"kind":"hololive-rhythm"}')
            report=cleanup_old_rhythm_logs(root,now=time.time()+100*86400,keep=0)
            self.assertEqual(report['removed'],1);self.assertFalse(p.exists())
    def test_release_worker_disables_full_per_key_file_audit_without_changing_engine(self):
        import numpy as np,time
        from test_rhythm_session import m
        from test_rhythm_live_review import FakeComputer,FakeVision
        from modular_agent.domains.hololive_dreams.multi_live import run_song
        from modular_agent.domains.hololive_dreams.rhythm_profile import load_profile
        root=Path(__file__).resolve().parents[1]
        class Capture:
            stats={'backend':'offline'};n=0;last_timestamp=None
            def bounds(self):return (0,0,320,180)
            def grab(self,roi):
                self.n+=1;self.last_timestamp=time.perf_counter()
                return np.zeros((180,320,3),np.uint8),self.bounds()
            def close(self):pass
        capture=Capture();computer=FakeComputer();vision=Mock()
        from types import SimpleNamespace
        vision.detect.return_value=SimpleNamespace(state='unknown',targets={})
        vision.gameplay_hud.return_value=True;vision.settlement.return_value=False
        values,_=load_profile(root)
        with tempfile.TemporaryDirectory() as folder,patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer) as factory,patch.object(m,'RhythmVision',FakeVision):
            run_song(root,7,vision,engine=m,overrides=values,wait_for_start=True,diagnostic_dir=Path(folder),cancelled=lambda:capture.n>=5,progress=lambda _:None)
            self.assertIs(m.ActionComputer,factory);self.assertIsNone(factory.call_args.kwargs['audit_path'])
            self.assertTrue(computer.closed)
    def test_rows_not_duplicated_in_summary_or_events(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=RhythmJournal(folder);directory=journal.song_directory('song-diagnostic-1-1')
            d=SongDiagnostics(emit=journal,directory=directory)
            d.finish({'reason':'cancelled','rows':['x'*1000000],'settings':{'old':1},'frames':100})
            summary=json.loads((directory/'summary.json').read_text())
            self.assertEqual(summary['result']['frames'],100);self.assertNotIn('rows',summary['result'])
            self.assertLess((journal.directory/'events.jsonl').stat().st_size,10000)
            self.assertLess((directory/'summary.json').stat().st_size,10000)
    def test_rotation_bounded_to_three_event_files(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=RhythmJournal(folder);journal.max_bytes=500
            for n in range(50):journal('test',index=n,data='x'*100)
            paths=list(journal.directory.glob('events*.jsonl'))
            self.assertEqual(len(paths),3)
            self.assertTrue(all(p.stat().st_size<1000 for p in paths))
            self.assertEqual(json.loads(paths[0].read_text().splitlines()[0])['event'],'test')
    def test_only_latest_three_song_attempts_keep_images(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=RhythmJournal(folder);paths=[]
            for n in range(5):
                path=journal.song_directory('song-diagnostic-'+str(n+1)+'-'+str(n));paths.append(path)
                (path/'gate-01.jpg').write_bytes(b'image');(path/'summary.json').write_text('{}')
            self.assertFalse((paths[0]/'gate-01.jpg').exists());self.assertFalse((paths[1]/'gate-01.jpg').exists())
            self.assertTrue(all((p/'summary.json').exists() for p in paths))
            self.assertTrue(all((p/'gate-01.jpg').exists() for p in paths[2:]))
    def test_disk_heartbeat_throttled_but_gate_change_kept(self):
        with tempfile.TemporaryDirectory() as folder:
            journal=RhythmJournal(folder)
            with patch('modular_agent.domains.hololive_dreams.rhythm_journal.time.monotonic',side_effect=[0,2,4,6,35]):
                for ready in (False,False,False,True,True):journal('rhythm_diagnostic',gate_ready=ready)
            self.assertEqual(len((journal.directory/'events.jsonl').read_text().splitlines()),2)
    def test_retention_only_removes_old_rhythm_and_preserves_recent_three(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);now=time.time();paths=[]
            for n in range(6):
                p=root/('20260101-00000'+str(n)+'-abcdef12');p.mkdir();paths.append(p)
                (p/'events.jsonl').write_text(json.dumps({'event':'rhythm_settings' if n!=1 else 'daily_task'}))
                age=now-(20-n)*86400
                os.utime(p/'events.jsonl',(age,age));os.utime(p,(age,age))
            recent=root/'20260102-000000-abcdef12';recent.mkdir();(recent/'events.jsonl').write_text('{"event":"rhythm_settings"}')
            report=cleanup_old_rhythm_logs(root,now=now)
            self.assertEqual(report['removed'],3)
            self.assertFalse(paths[0].exists());self.assertTrue(paths[1].exists());self.assertTrue(recent.exists())
            self.assertTrue(paths[4].exists());self.assertTrue(paths[5].exists())
    def test_unknown_folders_and_linked_contents_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'not-generated';p.mkdir();(p/'events.jsonl').write_text('{"event":"rhythm_settings"}')
            report=cleanup_old_rhythm_logs(root,now=time.time()+100*86400,keep=0)
            self.assertTrue(p.exists());self.assertEqual(report['removed'],0)
    def test_reparse_log_is_rejected_before_reading_or_deleting(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'20260101-000000-abcdef12';p.mkdir();(p/'events.jsonl').write_text('{"event":"rhythm_settings"}')
            with patch('modular_agent.domains.hololive_dreams.rhythm_journal._safe_files',side_effect=ValueError('linked child')):
                cleanup_old_rhythm_logs(root,now=time.time()+100*86400,keep=0)
            self.assertTrue(p.exists())
