import math,unittest
from test_rhythm_grid import m, ROOT

class GlobalFlowTests(unittest.TestCase):
    def config(self,mode='active'):
        return dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',global_flow=mode,
            motion_curve=dict(power=1,offset=0),hit_line_y=.8,input_offset_ms=10,dense_gap_ms=0)
    def flow_notes(self,y,other=None):
        return [m.Note(1,'tap',(.35,y),.06,.02,1,'blue'),
                m.Note(4,'tap',(.65,y if other is None else other),.06,.02,1,'blue')]
    def ready(self,mode='active'):
        c=m.RhythmController(self.config(mode));c.flow.rate=1.;c.flow.base=1.
        t=dict(id=1,lane=1,color='blue',kind='tap',fired=False,locked=True,arrival=.4,
            lock_until=.435,x=.35,y=.4,last=0.,phase_rate=1.,velocity=1.,normalized_width=.15)
        c.tracks=[t];return c,t

    def test_default_off_has_no_shared_model(self):
        c=m.RhythmController(m.load_config(ROOT));self.assertIsNone(c.flow)
    def test_shadow_never_changes_deadline(self):
        c,t=self.ready('shadow');c.flow.rate=.5;c.sync_global_flow(.13,dict(effective=.1))
        self.assertEqual(t['arrival'],.4);self.assertEqual(t['y'],.4)
    def test_half_speed_preserves_distance_at_actual_change(self):
        c,t=self.ready();c.flow.rate=.5;c.sync_global_flow(.13,dict(effective=.1))
        self.assertAlmostEqual(t['y'],.515);self.assertAlmostEqual(t['arrival'],.7)
        c.sync_global_flow(.15)
        self.assertAlmostEqual(t['y'],.525);self.assertAlmostEqual(t['arrival'],.7)
    def test_pending_up_gap_deadline_is_retimed(self):
        c,t=self.ready();t.update(held_ready=.39,held_target=.39,held_gap_started=.05,input_lane=1)
        c.held_pending['d']=(1,.39);c.flow.rate=.5;c.sync_global_flow(.13,dict(effective=.1))
        self.assertAlmostEqual(t['held_ready'],.69);self.assertAlmostEqual(c.held_pending['d'][1],.69)
    def test_stop_freezes_distance_and_resume_replans_press(self):
        c,t=self.ready();t.update(held_ready=.39,held_gap_started=.05,input_lane=1)
        c.held_pending['d']=(1,.39);c.flow.rate=0.;c.sync_global_flow(.13,dict(effective=.1))
        self.assertAlmostEqual(t['y'],.5);self.assertIsNone(t['arrival']);self.assertTrue(math.isinf(t['held_ready']))
        self.assertNotIn('d',c.poll(.2)['keys'])
        d=c.guard_baseline_restore(dict(keys=set(c.keys),events=[]),set(),.2)
        self.assertEqual(d['keys'],set())
        c.flow.rate=1.;c.sync_global_flow(.43,dict(effective=.4))
        self.assertAlmostEqual(t['y'],.53);self.assertAlmostEqual(t['arrival'],.7)
    def test_fired_heads_and_long_blind_tracks_not_rewritten(self):
        c,t=self.ready();t['fired']=True;c.flow.rate=.5;c.sync_global_flow(.1)
        self.assertEqual(t['arrival'],.4)
        t['fired']=False;c.sync_global_flow(2.01)
        self.assertIsNone(t['arrival']);self.assertFalse(t['locked'])
    def test_rate_change_needs_two_notes_three_consistent_intervals(self):
        c=m.RhythmController(self.config());f=c.flow;f.rate=2.;f.base=2.
        self.assertIsNone(f.observe(self.flow_notes(.2),0))
        self.assertIsNone(f.observe(self.flow_notes(.21),.01))
        self.assertIsNone(f.observe(self.flow_notes(.22),.02))
        e=f.observe(self.flow_notes(.23),.03)
        self.assertAlmostEqual(e['rate'],1.);self.assertAlmostEqual(e['multiplier'],.5)
        self.assertAlmostEqual(e['effective'],.005)
    def test_single_note_or_disagreement_cannot_switch_flow(self):
        c=m.RhythmController(self.config());f=c.flow;f.rate=2.;f.base=2.
        for i in range(6):
            self.assertIsNone(f.observe(self.flow_notes(.2+i*.01,.2+i*.02),i*.01))
        self.assertEqual(f.rate,2.)
        for i in range(6):self.assertIsNone(f.observe(self.flow_notes(.3+i*.01)[:1],.1+i*.01))
        self.assertEqual(f.rate,2.)
    def test_five_intervals_calibrate_without_bpm_mutation(self):
        c=m.RhythmController(self.config());f=c.flow
        for i in range(5):self.assertIsNone(f.observe(self.flow_notes(.2+i*.02),i*.01))
        self.assertAlmostEqual(f.observe(self.flow_notes(.3),.05)['rate'],2.)
        self.assertIsNone(c.grid.bpm)
    def test_unsupported_active_modes_rejected(self):
        for change in (dict(input_mode='normal'),dict(release_scope='all')):
            with self.assertRaises(ValueError):m.RhythmController(dict(self.config(),**change))

if __name__=='__main__':unittest.main()
