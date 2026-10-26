import unittest
from test_rhythm_grid import m, ROOT

class RestoreGuardTests(unittest.TestCase):
    def controller(self,scope='target'):
        return m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope=scope,input_offset_ms=0))

    def add_head(self,c,arrival=1.1,lane=3,colour='green',locked=True):
        y=.4;left,right=m.field_edges(c.c,y)
        t=dict(id=1,lane=lane,color=colour,kind='tap',fired=False,locked=locked,arrival=arrival,
            x=left+(lane+.5)/6*(right-left),y=y,normalized_width=1/6,last=1.,lock_until=1.5)
        c.tracks.append(t);return t

    def decision(self,c,events=None):return dict(keys=set(c.keys),events=events or [])

    def test_all_restore_sources_block_only_conflicting_new_downs(self):
        for scope in ('target','all'):
            for colour in ('blue','green','yellow','pink'):
                c=self.controller(scope);t=self.add_head(c,colour=colour)
                d=c.guard_baseline_restore(self.decision(c),set(),1.)
                expected={c.keys[i] for i in c.trigger_lanes(t)}
                self.assertEqual(set(c.keys)-d['keys'],expected)
                self.assertIn('j',d['restore_blocked'])

    def test_already_held_key_not_forced_up(self):
        c=self.controller();self.add_head(c)
        self.assertEqual(c.guard_baseline_restore(self.decision(c),set(c.keys),1.)['keys'],set(c.keys))

    def test_explicit_head_press_allowed_other_keys_still_checked(self):
        c=self.controller();self.add_head(c)
        d=self.decision(c,[dict(id=2,key='j',arrival=1.,time=1.)])
        out=c.guard_baseline_restore(d,set(),1.)
        self.assertIn('j',out['keys']);self.assertNotIn('k',out['keys'])

    def test_window_boundary_expiry_and_tail(self):
        for arrival,blocked in ((1.250,True),(1.251,False)):
            c=self.controller();self.add_head(c,arrival)
            self.assertEqual('j' not in c.guard_baseline_restore(self.decision(c),set(),1.)['keys'],blocked)
        for changes in (dict(fired=True),dict(ignored_reason='slide_end'),dict(lock_until=.99)):
            c=self.controller();self.add_head(c).update(changes)
            self.assertEqual(c.guard_baseline_restore(self.decision(c),set(),1.)['keys'],set(c.keys))

    def test_fresh_preliminary_curve_is_protected(self):
        c=self.controller();self.add_head(c,locked=False)
        self.assertNotIn('j',c.guard_baseline_restore(self.decision(c),set(),1.)['keys'])

    def test_pause_stale_recovery_is_based_on_actual_key_state(self):
        c=self.controller();t=self.add_head(c)
        first=c.guard_baseline_restore(self.decision(c),set(),1.)
        self.assertNotIn('j',first['keys'])
        t['fired']=True
        second=c.guard_baseline_restore(self.decision(c),first['keys'],1.12)
        self.assertIn('j',second['keys'])

    def test_key_up_and_normal_mode_unchanged(self):
        c=self.controller();self.add_head(c)
        self.assertEqual(c.guard_baseline_restore(dict(keys=set(),events=[]),set(c.keys),1.)['keys'],set())
        c.c['input_mode']='normal'
        self.assertEqual(c.guard_baseline_restore(self.decision(c),set(),1.)['keys'],set(c.keys))

    def test_recorded_2175_blocks_j_after_stale_release(self):
        c=self.controller();c.c['input_offset_ms']=75
        y=.3351851851851852;a,b=m.field_edges(c.c,y)
        c.tracks=[dict(id=2175,lane=4,color='blue',kind='tap',fired=False,locked=True,
            arrival=286.2353769268375,lock_until=286.2703769268375,
            x=.5927083333333333,y=y,normalized_width=.17916666666666667/(b-a),last=286.0)]
        result=c.guard_baseline_restore(self.decision(c),set(),286.04485215002205+.067)
        self.assertNotIn('j',result['keys'])
        self.assertEqual(result['restore_blocked']['j'],[2175])
        self.assertIn('s',result['keys']);self.assertIn('d',result['keys'])

if __name__=='__main__':unittest.main()
