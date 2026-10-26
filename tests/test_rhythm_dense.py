import unittest
from test_rhythm_global_release import m,ROOT

class DenseTests(unittest.TestCase):
    def make(self):
        c=m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope='all',input_offset_ms=10))
        c.tracks=[dict(id=i,lane=lane,color='blue',kind='tap',locked=True,lock_until=a+.035,arrival=a,last=.8,fired=False,prediction_source='middle_zone') for i,lane,a in [(1,1,1.),(2,4,1.06)]]
        return c
    def test_unoccupied_columns_stay_held(self):
        c=self.make();base=set()
        self.assertEqual(c.poll(.8)['keys'],base)
        d=c.poll(.990);self.assertEqual(d['keys'],base|{'d'})
        self.assertAlmostEqual(d['events'][0]['target'],.990)
        self.assertEqual(c.poll(1.01)['keys'],base)
        self.assertEqual(c.poll(1.0501)['keys'],base|{'k'})
        self.assertEqual(c.poll(1.18)['keys'],set(c.keys))
    def test_sparse(self):
        c=self.make();c.tracks[1]['arrival']=1.2
        self.assertEqual(c.poll(.8)['keys'],set(c.keys))
        self.assertEqual(c.poll(.95)['keys'],set())
        self.assertEqual(c.poll(.99)['keys'],set(c.keys))
        self.assertTrue(c.tracks[0]['fired'])
    def test_isolated_pink_represses_in_both_scopes(self):
        for scope in ('all','target'):
            c=self.make();c.c['release_scope']=scope;c.tracks=c.tracks[:1]
            c.tracks[0].update(color='pink',kind='pink_trial')
            c.poll(.8);self.assertNotIn('d',c.poll(.95)['keys'])
            d=c.poll(.99);self.assertIn('d',d['keys'])
            self.assertTrue(c.tracks[0]['fired'])
            self.assertAlmostEqual(d['events'][0]['target'],.99)
    def test_distant_key_remains_held_with_wider_keyboard(self):
        c=self.make();c.tracks[1]['lane']=2
        self.assertIn('l',c.poll(.8)['keys'])
        self.assertNotIn('s',c.poll(.81)['keys'])
    def test_cancel_pending(self):
        c=self.make();second=c.tracks.pop()
        c.all_release_batch={'tracks':[(c.tracks[0],.99)],'ready':.99,'min':.99,'max':.99}
        c.tracks.append(second)
        self.assertNotIn('d',c.poll(.97)['keys']);self.assertIsNone(c.all_release_batch)
        self.assertFalse(c.tracks[0]['fired'])
    def test_same_lane(self):
        c=self.make();c.tracks[1]['lane']=1;c.poll(.8)
        self.assertIn('d',c.poll(.990)['keys'])
        self.assertNotIn('d',c.poll(1.025)['keys'])
        self.assertIn('d',c.poll(1.0501)['keys'])
    def test_wide_note_blocks_neighbor(self):
        c=self.make();c.tracks[0].update(normalized_width=.5,y=.4)
        self.assertNotIn('f',c.poll(.8)['keys'])
    def test_isolated_slide_uses_normal_single_key_edge(self):
        c=self.make();c.tracks=c.tracks[:1];c.tracks[0]['kind']='hold'
        for now in (.8,.95,.99,1.,1.1):
            if now==.95:self.assertNotIn('d',c.poll(now)['keys'])
            else:c.poll(now)
        self.assertTrue(c.tracks[0]['fired'])
    def test_isolated_hold_uses_only_its_lane_edge(self):
        c=self.make();c.tracks=c.tracks[:1];c.tracks[0]['kind']='hold'
        c.c['release_scope']='target'
        c.poll(.8);d=c.poll(.95)
        self.assertNotIn('d',d['keys']);self.assertIn('s',d['keys'])
        d=c.poll(.99);self.assertIn('d',d['keys']);self.assertTrue(c.tracks[0]['fired'])
    def test_simultaneous_chord_is_not_a_dense_sequence(self):
        c=self.make();c.tracks[1]['arrival']=1.001
        self.assertEqual(c.poll(.95)['keys'],set())
        self.assertFalse(getattr(c,'dense_active',False))
        self.assertEqual(c.poll(.991)['keys'],set(c.keys))
        self.assertTrue(all(t['fired'] for t in c.tracks))
    def test_sparse_slide_does_not_extend_dense_protection(self):
        c=self.make();slide=dict(c.tracks[0],id=3,lane=5,arrival=2.,lock_until=2.035,kind='hold')
        c.tracks.append(slide);c.poll(.8);c.poll(.99);c.poll(1.0501)
        self.assertEqual(c.poll(1.18)['keys'],set(c.keys))
        self.assertFalse(slide['fired'])
        c.poll(1.95);c.poll(1.99)
        self.assertTrue(slide['fired'])
    def test_hold_and_tap_share_input_sequence(self):
        for scope in ('target','all'):
            for color in ('blue','green','yellow','pink'):
                sequences=[]
                for kind in ('tap','hold'):
                    c=self.make();c.c['release_scope']=scope;c.tracks=c.tracks[:1]
                    c.tracks[0].update(color=color,kind=kind)
                    sequences.append([c.poll(t)['keys'] for t in (.8,.95,.98,.99,1.01,1.1)])
                    self.assertTrue(c.tracks[0]['fired'])
                    self.assertFalse(c.holds)
                self.assertEqual(*sequences)
