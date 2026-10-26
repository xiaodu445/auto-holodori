import importlib.util,sys,unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('all_held_test_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class AllHeldTests(unittest.TestCase):
    def controller(self):return m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',input_offset_ms=10,dense_gap_ms=0,release_lead_ms=12))
    def track(self,ident=1,lane=2,arrival=1.,color='blue',locked=True):
        return dict(id=ident,lane=lane,color=color,kind='tap',locked=locked,arrival=arrival,last=.8,lock_until=arrival+.035,fired=False,prediction_source='middle_zone')
    def test_no_note_holds_baseline_without_periodic_spam(self):
        c=self.controller()
        for t in (.1,.2,1.,10.):
            d=c.poll(t);self.assertEqual(d['keys'],set(c.keys));self.assertEqual(d['events'],[])
    def test_targeted_gap_and_ten_ms_offset_unchanged(self):
        c=self.controller();c.tracks=[self.track()]
        self.assertEqual(c.poll(.97)['keys'],set(c.keys))
        d=c.poll(.98);self.assertEqual(d['keys'],set(c.keys)-{'f'})
        self.assertAlmostEqual(c.tracks[0]['held_target'],.99)
        self.assertNotIn('f',c.poll(.989)['keys'])
        d=c.poll(.99);self.assertEqual(d['keys'],set(c.keys))
        self.assertEqual(len([e for e in d['events'] if 'arrival' in e]),1)
        self.assertEqual(c.poll(1.)['events'],[])
    def test_chord_opens_only_target_keys(self):
        c=self.controller();c.tracks=[self.track(1,1),self.track(2,4)]
        self.assertEqual(c.poll(.98)['keys'],set(c.keys)-{'d','k'})
        self.assertEqual(c.poll(.99)['keys'],set(c.keys))
    def test_lost_unconfirmed_note_does_not_create_gap(self):
        c=self.controller();c.tracks=[self.track(locked=False)]
        self.assertEqual(c.poll(.98)['keys'],set(c.keys));self.assertEqual(c.held_pending,{})
    def test_orphan_pending_track_restores_baseline(self):
        c=self.controller();c.tracks=[self.track()];c.poll(.98);c.tracks=[]
        self.assertNotIn('f',c.poll(.989)['keys'])
        self.assertEqual(c.poll(.99)['keys'],set(c.keys))
    def test_repeated_same_key_gets_up_down_edges(self):
        c=self.controller();c.tracks=[self.track(1,2,1.),self.track(2,2,1.0625)]
        calls=[]
        class Computer:
            def perform(self,a):
                calls.append((a.name,a.arguments['key']));return SimpleNamespace(outcome=m.Outcome.SUCCESS,message='test')
        keys=m.KeyState(Computer(),True,c.keys)
        for now in (.97,.98,.99,1.041,1.05,1.0526):keys.update(c.poll(now)['keys'])
        self.assertEqual([name for name,key in calls if key=='f'],['key_down','key_up','key_down','key_up','key_down'])
        keys.release();self.assertFalse(keys.down)
        self.assertEqual(len([1 for name,key in calls if name=='key_up']),8)
    def test_same_key_duplicate_heads_coalesce(self):
        c=self.controller();c.tracks=[self.track(1),self.track(2,color='yellow')]
        c.poll(.98);d=c.poll(.99)
        self.assertEqual(d['keys'],set(c.keys));self.assertEqual(len([e for e in d['events'] if 'arrival' in e]),1)
        self.assertTrue(all(t['fired'] for t in c.tracks));self.assertFalse(c.held_pending)
    def test_late_observation_keeps_minimum_release_window(self):
        c=self.controller();c.tracks=[self.track()]
        self.assertNotIn('f',c.poll(.989)['keys'])
        self.assertNotIn('f',c.poll(.990)['keys'])
        self.assertNotIn('f',c.poll(.996)['keys'])
        self.assertIn('f',c.poll(.998)['keys'])
    def test_old_mode_stays_default(self):
        c=m.RhythmController(m.load_config(ROOT))
        self.assertEqual(c.poll(0)['keys'],set())
    def test_runtime_stop_releases_all_six_keys(self):
        from unittest.mock import patch
        from test_rhythm_live_review import FakeCapture,FakeComputer,FakeVision
        capture=FakeCapture();computer=FakeComputer()
        with patch.object(m,'create_capture',return_value=capture),patch.object(m,'ActionComputer',return_value=computer),patch.object(m,'RhythmVision',FakeVision):
            result=m.run(ROOT,123,live=True,overrides={'input_mode':'all-held','timeout':1,'fps':120})
        self.assertEqual(result['reason'],'test_focus_lost')
        for key in m.load_config(ROOT)['keys']:
            self.assertEqual([name for name,k in computer.calls if k==key],['key_down','key_up'])
        self.assertTrue(computer.closed);self.assertTrue(capture.closed)

if __name__=='__main__':unittest.main()
