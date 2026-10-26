import importlib.util,sys,unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('global_release_test_model',ROOT/'domains/hololive_dreams/models/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class GlobalReleaseTests(unittest.TestCase):
    def controller(self):return m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope='all',input_offset_ms=10,dense_gap_ms=0,release_lead_ms=30))
    def track(self,ident=1,lane=2,arrival=1.):
        return dict(id=ident,lane=lane,color='blue',kind='tap',locked=True,lock_until=arrival+.035,arrival=arrival,last=.8,fired=False,prediction_source='middle_zone')
    def test_all_release_at_thirty_ms_lead_restore_at_offset_target(self):
        c=self.controller();c.tracks=[self.track()]
        self.assertEqual(c.poll(.95)['keys'],set(c.keys))
        self.assertEqual(c.poll(.965)['keys'],set())
        self.assertEqual(c.poll(.98)['keys'],set())
        d=c.poll(.99);self.assertEqual(d['keys'],set(c.keys));self.assertAlmostEqual(d['events'][0]['target'],.99)
        self.assertEqual(c.poll(.995)['events'],[])
    def test_chord_has_one_release_window_not_sequential_repress(self):
        c=self.controller();c.tracks=[self.track(1,1),self.track(2,4,1.001)]
        d=c.poll(.965);self.assertEqual(d['keys'],set());self.assertEqual(d['events'][0]['ids'],[1,2])
        self.assertFalse(c.poll(.989)['keys'])
        d=c.poll(.992);self.assertEqual(d['keys'],set(c.keys));self.assertEqual(len(d['events']),2)
    def test_physical_requests_all_up_then_all_down(self):
        c=self.controller();c.tracks=[self.track()];calls=[]
        class Computer:
            def perform(self,a):
                calls.append((a.name,a.arguments['key']));return SimpleNamespace(outcome=m.Outcome.SUCCESS,message='mock')
        keys=m.KeyState(Computer(),True,c.keys)
        for now in (.95,.965,.99):keys.update(c.poll(now)['keys'])
        self.assertEqual(len(calls),18)
        self.assertTrue(all(name=='key_up' for name,_ in calls[6:12]))
        self.assertTrue(all(name=='key_down' for name,_ in calls[12:18]))
        keys.release();self.assertFalse(keys.down)
    def test_disappearing_track_does_not_leave_everything_released(self):
        c=self.controller();c.tracks=[self.track()];c.poll(.965);c.tracks.clear()
        self.assertEqual(c.poll(.99)['keys'],set(c.keys))
    def test_unconfirmed_and_expired_heads_do_not_open_global_gap(self):
        c=self.controller();t=self.track();t['locked']=False;c.tracks=[t]
        self.assertEqual(c.poll(.97)['keys'],set(c.keys))
        t['locked']=True;self.assertEqual(c.poll(2.)['keys'],set(c.keys))
    def test_successive_heads_restore_before_next_release(self):
        c=self.controller();c.tracks=[self.track(),self.track(2,4,1.0625)]
        for now in (.965,.99,1.025,1.0526):d=c.poll(now)
        self.assertEqual(d['keys'],set(c.keys));self.assertTrue(all(t['fired'] for t in c.tracks))
    def test_ten_ms_is_one_group_but_thirty_ms_is_two(self):
        c=self.controller();c.tracks=[self.track(1,1),self.track(2,4,1.010),self.track(3,2,1.030)]
        events=c.poll(.965)['events'];self.assertEqual(events[0]['ids'],[1,2])
        first=c.poll(.996);self.assertEqual(first['keys'],set(c.keys))
        self.assertFalse(c.tracks[2]['fired'])
        second=c.poll(1.001);self.assertEqual(second['keys'],set());self.assertEqual(second['events'][0]['ids'],[3])
        self.assertEqual(c.poll(1.0201)['keys'],set(c.keys))
    def test_pending_group_accepts_later_confirmation_without_delaying(self):
        c=self.controller();c.tracks=[self.track(1,1)];c.poll(.965)
        ready=c.all_release_batch['ready'];c.tracks.append(self.track(2,4,1.009))
        c.poll(.98);self.assertEqual(c.all_release_batch['ready'],ready)
        self.assertEqual(len(c.all_release_batch['tracks']),2)
        self.assertEqual(c.poll(.991)['keys'],set(c.keys));self.assertTrue(all(t['fired'] for t in c.tracks))
    def test_completed_group_absorbs_late_track_without_second_pulse(self):
        c=self.controller();c.tracks=[self.track(1,1)];c.poll(.965);c.poll(.99)
        c.tracks.append(self.track(2,4,1.008))
        result=c.poll(.995);self.assertEqual(result['keys'],set(c.keys))
        self.assertEqual(result['events'][0]['type'],'coalesced_late_group_head');self.assertTrue(c.tracks[1]['fired'])
        self.assertIsNone(c.all_release_batch)
    def test_pairwise_proximity_does_not_chain_into_a_larger_group(self):
        c=self.controller();c.tracks=[self.track(1,1),self.track(2,4,1.009)]
        c.poll(.965);c.tracks.append(self.track(3,2,1.018));c.poll(.98)
        self.assertEqual(len(c.all_release_batch['tracks']),2)
        self.assertLessEqual(c.all_release_batch['max']-c.all_release_batch['min'],.010000001)
    def test_current_zero_offset_remains_zero_not_merge_window_compensation(self):
        config=dict(m.load_config(ROOT),input_mode='all-held',release_scope='all',dense_gap_ms=0)
        config['input_offset_ms']=0
        c=m.RhythmController(config);c.tracks=[self.track()]
        c.poll(.975);self.assertFalse(c.poll(.995)['keys'])
        d=c.poll(1.);self.assertEqual(d['keys'],set(c.keys));self.assertAlmostEqual(d['events'][0]['target'],1.)

if __name__=='__main__':unittest.main()
