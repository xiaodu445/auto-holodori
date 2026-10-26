import unittest
from test_rhythm_grid import m, ROOT

class PinkChordTests(unittest.TestCase):
    def controller(self,**kwargs):
        return m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',
            input_offset_ms=0,release_lead_ms=20,dense_gap_ms=kwargs.get('dense',0)))

    def notes(self,colour='pink',lanes=(0,1,2),different_rows=False):
        ns=[]
        for i,lane in enumerate(lanes):
            y=.3+i*.03 if different_rows else .3
            left,right=m.field_edges(m.load_config(ROOT),y)
            ns.append(m.Note(lane,'pink_trial' if colour=='pink' else 'tap',
                (left+(lane+.5)/6*(right-left),y),(right-left)/6,.02,1.,colour))
        return ns

    def arm(self,c,notes):
        c.decide(notes,0);c.decide(notes,.015)
        for t in c.tracks:t.update(locked=True,arrival=.1+(t['lane']-1)*.015,lock_until=.3)

    def test_three_flicks_one_d_despite_separate_fit_errors(self):
        c=self.controller();self.arm(c,self.notes())
        # S/D/F share D; the following green must not get an F re-press.
        for now in (.08,.10,.12,.14):
            out=c.poll(now)
            if now==.08:self.assertEqual(set(c.keys)-out['keys'],{'d'})
            if now==.10:
                self.assertEqual([e['key'] for e in out['events'] if 'arrival' in e],['d'])
                self.assertEqual(len([e for e in out['events'] if e.get('type')=='pink_chord_covered']),2)
            self.assertFalse(any(e.get('key')=='f' for e in out['events']))
        self.assertTrue(all(t['fired'] for t in c.tracks))

    def test_blue_green_yellow_not_shared(self):
        for colour in ('blue','green','yellow'):
            c=self.controller();self.arm(c,self.notes(colour))
            self.assertTrue(all('pink_chord_leader' not in t for t in c.tracks))

    def test_separate_rows_and_no_common_footprint_stay_separate(self):
        for ns in (self.notes(different_rows=True),self.notes(lanes=(0,5))):
            c=self.controller();self.arm(c,ns)
            self.assertTrue(all('pink_chord_leader' not in t for t in c.tracks))

    def test_single_frame_cannot_form_group(self):
        c=self.controller();c.decide(self.notes(),0)
        self.assertTrue(all('pink_chord_leader' not in t for t in c.tracks))

    def test_dense_path_also_omits_followers(self):
        c=self.controller(dense=100);self.arm(c,self.notes())
        # With followers excluded there is no fabricated successive cluster.
        self.assertIsNone(c.poll_dense_heads(.08))

if __name__=='__main__':unittest.main()
