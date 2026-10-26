import unittest
from types import SimpleNamespace
from test_rhythm_grid import m,ROOT

class MechanismTests(unittest.TestCase):
    def test_live_experiment_launcher_forces_mechanism_off(self):
        command=(ROOT/'run_rhythm_mechanism_test.cmd').read_text(encoding='utf-8')
        self.assertNotIn('--mechanism-mode active',command)
        self.assertIn('%* --mechanism-mode off',command)
    def test_disabled_controller_has_no_mechanism_or_fill(self):
        c=m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',mechanism_mode='off'))
        self.assertIsNone(c.mechanism)
        self.assertEqual(c.mechanism_fill_heads(1.),[])
    def check(self,gaps,step=.125,rate=2.,now=1.1,rates=None,epoch=None):
        mech=m.MechanismCadence('active');arrival=1.
        for i,gap in enumerate((0.,)+gaps):
            arrival+=gap
            mech.observe(dict(id=i+1,color='blue',normalized_width=1.),arrival,1.,arrival+.02)
        clock=SimpleNamespace(step=step,epoch=epoch,status=lambda now:dict(pulse_ms=125.),flow_change=lambda event:None)
        event=None
        for i,value in enumerate(rates if rates is not None else [rate-i*.04 for i in range(10)]):
            stamp=now+i*.015
            result=mech.start(None,clock,SimpleNamespace(last_sample=(stamp,value)),stamp,phase_anchor=(2,99.))
            if result:event=result
        return mech,event
    def test_fractional_shrinking_ceil_and_first_raw_anchor(self):
        mech,event=self.check((.3125,.28))
        self.assertEqual(event['stride'],3)
        self.assertEqual(list(mech.plan['slots'].values()),[1.3125,1.6875])
    def test_integer_and_nonshrinking_gaps_do_not_veto_visual_trigger(self):
        for gaps in ((.38,.369),(.3125,.25),(.3125,.31),(.28,.3125),(.375,.375)):
            self.assertIsNotNone(self.check(gaps)[1])
    def test_rounding_uses_grid_cell_not_double_pulse(self):
        mech,event=self.check((.3125,.15625),step=.0625)
        self.assertEqual(event['interval_ms'],187.5)
        self.assertEqual(event['stride'],3)
        self.assertEqual(mech.plan['grid_step_ms'],62.5)
    def test_near_integer_error_does_not_add_a_cell(self):
        self.assertEqual(self.check((.3,.190),step=.0625)[1]['interval_ms'],187.5)
    def test_anchor_snapped_once_and_later_slots_stay_on_grid(self):
        epoch=.010;step=.0625
        mech,event=self.check((.3125,.15625),step=step,epoch=epoch)
        self.assertAlmostEqual(event['anchor'],1.3225)
        self.assertAlmostEqual(event['anchor_correction_ms'],10.)
        t=dict(id=4,color='blue',fired=False,history=[1,2,3],lane=2)
        mech.assign([t],1.3)
        for arrival in mech.plan['slots'].values():
            ticks=(arrival-epoch)/step
            self.assertAlmostEqual(ticks,round(ticks))
        self.assertAlmostEqual(mech.plan['slots'][4]-mech.plan['slots'][3],.1875)
    def test_anchor_snaps_backward_without_changing_interval(self):
        mech,event=self.check((.3125,.15625),step=.0625,epoch=-.010)
        self.assertAlmostEqual(event['anchor_correction_ms'],-10.)
        self.assertAlmostEqual(event['interval_ms'],187.5)
    def test_stop_and_stale(self):
        self.assertIsNone(self.check((.3125,.28),rates=[0.]*12)[1])
        self.assertIsNone(self.check((.3125,.28),now=9.)[1])
    def test_assign_preserves_column_and_expires(self):
        mech,event=self.check((.3125,.28))
        t=dict(id=4,lane=4,color='blue',fired=False,normalized_width=1.,history=[1,2,3])
        self.assertEqual(mech.assign([t],1.2),[(t,2.0625)])
        self.assertEqual(t['lane'],4)
        self.assertEqual(mech.assign([t],6.),[])
    def test_flat_jump_acceleration_and_jitter_do_not_trigger(self):
        for rates in ([2.]*20,[2.]*8+[1.]*12,[2.]*8+[0.]*12,
                      [1.+i*.04 for i in range(12)],[2.,1.99]*8):
            self.assertIsNone(self.check((.3125,.28),rates=rates)[1])
    def test_duplicate_sample_cannot_create_visual_evidence(self):
        mech=m.MechanismCadence('active')
        clock=SimpleNamespace(step=.125)
        for _ in range(15):
            self.assertIsNone(mech.start(None,clock,SimpleNamespace(last_sample=(1.,2.)),1.))
        self.assertEqual(len(mech.speeds),1)
    def test_old_large_gap_is_not_used(self):
        mech,event=self.check((.4767,.1752))
        self.assertAlmostEqual(event['interval_ms'],250.)
        self.assertEqual(event['anchor_id'],2)
    def test_narrow_and_other_colors_are_kept_but_tails_are_not(self):
        mech=m.MechanismCadence('active')
        for identity,color,kind in ((1,'blue','tap'),(2,'green','hold'),(3,'pink','pink_trial'),(4,'yellow','slide_end')):
            mech.observe(dict(id=identity,color=color,kind=kind,normalized_width=.16),identity*.1,0.)
        self.assertEqual([i for i,_ in mech.records],[1,2,3])
