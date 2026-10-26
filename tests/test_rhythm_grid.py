import importlib.util,sys,unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('grid_test_model',ROOT/'domains/hololive_dreams/models/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class BeatGridTests(unittest.TestCase):
    def feed(self,grid,period=.0625,count=64,start=10.):
        rng=np.random.default_rng(42);n=0
        for i in range(count):
            n+=(1,2,2,4,3)[i%5]
            grid.observe(start+n*period+rng.normal(0,.0015))
        return grid
    def test_noisy_lattice_locks_without_claiming_bpm(self):
        grid=self.feed(m.BeatGrid())
        self.assertTrue(grid.locked)
        self.assertAlmostEqual(grid.period,.0625,delta=.0001)
        self.assertGreater(grid.confidence,.7)
        self.assertIsNone(grid.bpm)
        self.assertFalse(grid.status()['bpm_confirmed'])
    def test_chords_and_bad_values_do_not_train(self):
        grid=m.BeatGrid()
        for _ in range(100):grid.observe(1.)
        grid.observe(float('nan'));grid.observe(float('inf'))
        self.assertEqual(len(grid.arrivals),1)
        self.assertFalse(grid.locked)
        self.assertEqual(grid.nearest(1.002),1.002)
    def test_wrong_first_onset_does_not_anchor_phase(self):
        grid=m.BeatGrid();grid.observe(10.023)
        for i in range(1,65):grid.observe(10+i*.0625)
        self.assertTrue(grid.locked)
        self.assertAlmostEqual(grid.period,.0625,delta=.00005)
        self.assertAlmostEqual(grid.nearest(14.002),14.,delta=.0001)
    def test_sparse_harmonic_is_not_claimed_as_true_bpm(self):
        grid=self.feed(m.BeatGrid(),period=.125)
        self.assertTrue(grid.locked)
        self.assertAlmostEqual(grid.period,.125,delta=.0002)
        self.assertIsNone(grid.bpm)
        self.assertGreaterEqual(len(grid.candidates),2)
    def test_only_three_ms_and_no_pull_from_distant_notes(self):
        grid=self.feed(m.BeatGrid());target=grid.phase+round((20-grid.phase)/grid.period)*grid.period
        self.assertAlmostEqual(grid.nearest(target+.002),target)
        self.assertEqual(grid.nearest(target+.010),target+.010)
        for delta in np.linspace(-.04,.04,101):
            self.assertLessEqual(abs(grid.nearest(target+delta)-(target+delta)),.00300001)
    def test_three_contradictions_disable_then_relearn(self):
        grid=self.feed(m.BeatGrid());start=max(grid.arrivals)+.5
        for i in range(3):grid.observe(start+i*.25+.027)
        self.assertFalse(grid.locked)
        self.feed(grid,period=.0833333333,count=80,start=start+2.)
        self.assertTrue(grid.locked)
        self.assertAlmostEqual(grid.period,.0833333333,delta=.0002)
    def test_custom_window_disabled_and_unlocked(self):
        grid=m.BeatGrid(16,240,snap_ms=8)
        self.assertEqual(grid.nearest(1.0685),1.0685)
        grid.observe(1.)
        self.assertAlmostEqual(grid.nearest(1.0685),1.0625)
        self.assertEqual(grid.nearest(1.0745),1.0745)
        self.assertEqual(grid.status()['snap_limit_ms'],8)
        disabled=m.BeatGrid(16,240,snap_ms=0);disabled.observe(1.)
        self.assertTrue(disabled.locked)
        self.assertEqual(disabled.nearest(1.0645),1.0645)
        self.assertEqual(disabled.status()['snap_limit_ms'],0)
    def test_half_grid_guard_and_validation(self):
        grid=m.BeatGrid(16,400,snap_ms=25);grid.observe(1.)
        self.assertAlmostEqual(grid.status()['snap_limit_ms'],18.375)
        self.assertEqual(grid.nearest(1.01875),1.01875)
        for value in (-1,26,float('nan'),float('inf'),True):
            with self.subTest(value=value),self.assertRaises(ValueError):m.BeatGrid(snap_ms=value)
    def test_controller_uses_configured_window(self):
        c=m.RhythmController(dict(m.load_config(ROOT),bpm=240,grid_snap_ms=8))
        c.grid.observe(1.)
        self.assertAlmostEqual(c.grid.nearest(1.0685),1.0625)
    def test_random_times_do_not_lock(self):
        grid=m.BeatGrid();rng=np.random.default_rng(3)
        for value in np.cumsum(rng.uniform(.06,.4,100)):grid.observe(float(value))
        self.assertFalse(grid.locked)
    def test_no_notes_never_creates_input(self):
        controller=m.RhythmController(m.load_config(ROOT));self.feed(controller.grid)
        for time in np.arange(20.,21.,.001):
            self.assertEqual(controller.poll(float(time))['events'],[])
    def test_known_bpm_contradiction_disables_correction(self):
        grid=m.BeatGrid(16,240);grid.observe(1.)
        self.assertAlmostEqual(grid.nearest(1.0645),1.0625)
        for t in (1.15,1.275,1.4):grid.observe(t)
        self.assertFalse(grid.locked)
        self.assertEqual(grid.nearest(1.502),1.502)

if __name__=='__main__':unittest.main()
