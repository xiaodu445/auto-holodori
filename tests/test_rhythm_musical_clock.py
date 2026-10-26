import unittest
from test_rhythm_grid import m, ROOT

class MusicalClockTests(unittest.TestCase):
    def learned(self):
        c=m.MusicalClock(m.load_config(ROOT))
        for i in range(64):c.observe(10+i*.125,10+i*.125,2)
        self.assertIsNotNone(c.step)
        return c
    def test_uniform_pulses_cannot_prove_downbeat(self):
        c=self.learned();s=c.status(18.)
        self.assertEqual(s['state'],'tracking');self.assertTrue(s['bar_ambiguous'])
        self.assertEqual(s['bar_confidence'],0.)
        self.assertEqual({x['bar_ticks'] for x in s['candidates']},{8,16})
        self.assertTrue(all(x['next_bar']>18 for x in s['candidates']))
    def test_scroll_freezes_learning_not_clock_progress(self):
        c=self.learned();step,epoch=c.step,c.epoch
        c.flow_change(dict(time=18.,old_rate=3.,rate=.5))
        c.observe(99.,19.,1)
        a,b=c.status(19.),c.status(20.)
        self.assertEqual((c.step,c.epoch),(step,epoch))
        self.assertEqual(a['state'],'holdover');self.assertGreater(b['step_index'],a['step_index'])
        self.assertFalse(a['sends_input'])
    def test_chord_is_one_onset_multiple_lanes(self):
        c=m.MusicalClock(m.load_config(ROOT));c.observe(10,9.8,1);c.observe(10.003,9.81,3)
        self.assertEqual(len(c.rows),1);self.assertEqual(c.rows[0]['lanes'],{1,3})
    def test_dense_notes_do_not_double_tempo_after_lock(self):
        c=self.learned();step=c.step
        for i in range(32):c.observe(18+i*.0625,18+i*.0625,2)
        self.assertEqual(c.step,step)
    def test_controller_shadow_does_not_change_decisions(self):
        cfg=dict(m.load_config(ROOT),input_mode='all-held',dense_gap_ms=0)
        a,b=m.RhythmController(cfg),m.RhythmController(dict(cfg,measure_clock='shadow'))
        for i in range(30):
            y=.15+i*.012
            ns=[m.Note(2,'tap',(.45,y),.08,.02,1.,'blue')]
            da,db=a.decide(ns,i*.015),b.decide(ns,i*.015)
            self.assertEqual(da['keys'],db['keys']);self.assertEqual(da['events'],db['events'])
            self.assertIn('music_clock',db)
    def test_suspended_learning_can_resume_if_no_clock_was_available(self):
        c=m.MusicalClock(m.load_config(ROOT));c.flow_change(dict(time=0.,old_rate=3.,rate=1.5))
        c.observe(1.,1.,1);self.assertEqual(len(c.rows),0)
        c.observe(3.,3.,1);self.assertEqual(len(c.rows),1)

if __name__=='__main__':unittest.main()
