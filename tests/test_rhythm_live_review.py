import importlib.util,json,queue,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rhythm_live_review as live
m=live.review.load_model()

class FakeComputer:
    stopped=False
    def __init__(self):self.calls=[];self.closed=False;self.fail_key=None
    def perform(self,action):
        self.calls.append((action.name,action.arguments['key']))
        outcome=m.Outcome.FAILURE if action.arguments['key']==self.fail_key else m.Outcome.SUCCESS
        return SimpleNamespace(outcome=outcome,message='mock result')
    def close(self):self.closed=True

class FakeCapture:
    def __init__(self):self.n=0;self.closed=False;self.stats={'backend':'test'};self.last_timestamp=None
    def bounds(self):return (0,0,320,180)
    def grab(self,roi):
        self.n+=1
        if self.n>4:raise RuntimeError('test_focus_lost')
        self.last_timestamp=time.perf_counter()
        return np.zeros((180,320,3),np.uint8),self.bounds()
    def close(self):self.closed=True

class FakeVision:
    hold_paths=[]
    def __init__(self,c):pass
    def detect(self,image,stamp):return []

class FakeController:
    tracks=[]
    grid=SimpleNamespace(bpm=None)
    def __init__(self,c):pass
    def poll(self,t):return {'keys':{'f'},'events':[],'holds':[],'bpm':None,'grid':{}}
    def decide(self,*args,**kwargs):return self.poll(0)
    def guard_baseline_restore(self,decision,actual_down,now):return decision

class LiveReviewTests(unittest.TestCase):
    def test_gap_resume_timestamp_is_relative_not_absolute(self):
        sink=object.__new__(live.LiveDiagnostics);sink.origin=100.
        event=sink.relative_event(dict(time=101.,target=101.02,resume=101.03,lateness_ms=3.))
        self.assertAlmostEqual(event['time'],1.);self.assertAlmostEqual(event['resume'],1.03)
        self.assertEqual(event['lateness_ms'],3.)
    def test_no_record_never_constructs_recorder_or_output_directory(self):
        for switches in (['--no-record'],['--record','--no-record']):
            with self.subTest(switches=switches),tempfile.TemporaryDirectory() as tmp:
                output=Path(tmp)/'must-not-exist'
                backend=SimpleNamespace(windows=lambda:[dict(title='hololive-Dreams',handle=123)],api=SimpleNamespace(GetForegroundWindow=lambda:123))
                with patch('modular_agent.computer.windows.WindowsBackend',return_value=backend),patch.object(live.review,'load_model') as model,patch.object(live,'LiveDiagnostics',side_effect=AssertionError('recorder forbidden')),patch.object(sys,'argv',['rhythm_live_review.py','--live','--input-mode','all-held','--fps','90','--analysis-width','720','--release-lead-ms','80','--offset-ms','10','--grid-snap-ms','8','--output',str(output),*switches]):
                    model.return_value.run.return_value={'reason':'mock_stopped','rows':[]}
                    live.main()
                    self.assertIsNone(model.return_value.run.call_args.kwargs['diagnostics'])
                    self.assertEqual(model.return_value.run.call_args.kwargs['overrides']['input_mode'],'all-held')
                    config=model.return_value.run.call_args.kwargs['overrides']
                    self.assertEqual(config['grid_snap_ms'],8)
                    self.assertEqual((config['fps'],config['analysis_width'],config['release_lead_ms'],config['input_offset_ms']),(90,720,80,10))
                    self.assertTrue(model.return_value.run.call_args.kwargs['live'])
                self.assertFalse(output.exists())
    def test_partial_input_failure_retains_owned_key_for_release(self):
        computer=FakeComputer();computer.fail_key='j';events=[]
        keys=m.KeyState(computer,True,['f','j'],on_send=events.append)
        with self.assertRaises(RuntimeError):keys.update({'f','j'})
        self.assertEqual(keys.down,{'f'})
        keys.release();self.assertEqual(keys.down,set())
        self.assertEqual(computer.calls,[('key_down','f'),('key_down','j'),('key_up','f')])
        self.assertEqual([e['success'] for e in events],[True,False,True])
        self.assertTrue(all(e['begin']<=e['time'] for e in events))
    def test_dry_keys_do_not_emit_real_input_evidence(self):
        computer=FakeComputer();events=[];keys=m.KeyState(computer,False,['f'],events.append)
        keys.update({'f'});keys.release()
        self.assertEqual(events,[]);self.assertEqual(computer.calls,[])
    def test_one_failed_release_does_not_skip_other_owned_keys(self):
        computer=FakeComputer();keys=m.KeyState(computer,True,['f','j'])
        keys.update({'f','j'});computer.fail_key='f'
        with self.assertRaises(RuntimeError):keys.release()
        self.assertEqual(computer.calls[-2:],[('key_up','f'),('key_up','j')])
        self.assertEqual(keys.down,{'f'})
    def test_logging_error_after_key_down_still_releases_it(self):
        class BrokenLog:
            failed=False
            def input_edge(self,e):self.failed=True
            def check(self):
                if self.failed:raise RuntimeError('test_logging_error')
            def frame(self,*args):self.check()
        computer=FakeComputer();capture=FakeCapture();sink=BrokenLog()
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision),patch.object(m,'RhythmController',FakeController):
            result=m.run(ROOT,123,live=True,overrides={'fps':120,'timeout':1,'analysis_width':320},diagnostics=sink)
        self.assertIn('test_logging_error',result['reason'])
        self.assertEqual(computer.calls,[('key_down','f'),('key_up','f')])
        self.assertTrue(computer.closed);self.assertTrue(capture.closed)
    def test_stop_arriving_during_capture_prevents_another_press(self):
        computer=FakeComputer();capture=FakeCapture()
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision),patch.object(m,'RhythmController',FakeController):
            result=m.run(ROOT,123,live=True,overrides={'fps':120,'timeout':1,'analysis_width':320},should_yield=lambda:capture.n>=2)
        self.assertIn(result['reason'],('cancelled','cancelled_before_input'))
        self.assertEqual(computer.calls,[('key_down','f'),('key_up','f')])
        self.assertTrue(computer.closed);self.assertTrue(capture.closed)
    def test_queue_overload_does_not_throw_inside_input_callback(self):
        sink=object.__new__(live.LiveDiagnostics);sink.items=queue.Queue(1);sink.items.put('full');sink.error=None;sink.closed=False
        sink.input_edge({'key':'f','down':True,'time':0,'begin':0,'success':True})
        self.assertIn('queue full',sink.error)
        with self.assertRaises(RuntimeError):sink.check()
    def test_live_run_uses_one_capture_and_logs_final_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'live';sink=live.LiveDiagnostics(output);computer=FakeComputer();capture=FakeCapture()
            with patch.object(m,'create_capture',return_value=capture) as factory,patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision),patch.object(m,'RhythmController',FakeController):
                result=m.run(ROOT,123,live=True,overrides={'fps':120,'timeout':1,'analysis_width':320},diagnostics=sink)
            self.assertEqual(factory.call_count,1)
            self.assertTrue(computer.closed);self.assertTrue(capture.closed)
            self.assertEqual(computer.calls,[('key_down','f'),('key_up','f')])
            page=sink.finish(m.load_config(ROOT),result)
            self.assertTrue(page.exists())
            data=json.loads((output/'analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(data['mode'],'live');self.assertEqual(len(data['frames']),4)
            self.assertEqual([e['down'] for e in data['recorded_input_edges']],[True,False])
            self.assertTrue(all(not e['simulated'] for e in data['input_attempts']))
            self.assertEqual(data['reason'],'test_focus_lost')
            html=(output/'part-0001.html').read_text(encoding='utf-8')
            self.assertIn('当次运行记录',html);self.assertIn("value='recorded'",html)
            self.assertEqual(len((output/'live-decisions.jsonl').read_text(encoding='utf-8').splitlines()),6)
    def test_worker_failure_stops_checks_and_closes_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink=live.LiveDiagnostics(Path(tmp)/'failed')
            decision=dict(events=[],holds=[],grid={},bpm=None)
            with patch.object(live.cv2,'imwrite',return_value=False):
                sink.frame(np.zeros((100,100,3),np.uint8),time.perf_counter(),[0,0,100,100],[],[],decision,[],{'capture':0,'vision':0,'input':0})
                sink.thread.join(timeout=3)
            with self.assertRaisesRegex(RuntimeError,'frame export'):sink.check()
            with self.assertRaises(RuntimeError):sink.finish(m.load_config(ROOT),{'reason':'error'})
            self.assertFalse(sink.thread.is_alive())

if __name__=='__main__':unittest.main()
