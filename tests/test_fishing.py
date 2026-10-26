import unittest
from pathlib import Path
import tempfile
import json
import numpy as np
from modular_agent.realtime.fishing import load,crop
from modular_agent.realtime.runtime import InputLatch,run_loop
from modular_agent.perception.screen import load_image
from modular_agent.computer import ActionComputer
from test_computer import FakeBackend

ROOT=Path(__file__).resolve().parents[1]
class FishingTests(unittest.TestCase):
    def setUp(self): self.c,self.m,self.v=load(ROOT); self.c.update(pwm_hover_duty=.5,pwm_position_gain=1.5,pwm_velocity_gain=.25)
    def image(self,name): return load_image(ROOT/f'domains/hololive_dreams/data/fishing_samples/{name}.png')[44:]
    def test_attached_frames_and_scaled_recognition(self):
        import cv2
        for scale in (1,.75,1.5):
            im=cv2.resize(self.image('control'),None,fx=scale,fy=scale)
            o=self.v.control(crop(im,self.c['control_roi']))
            self.assertTrue(o['valid']); self.assertAlmostEqual(o['center'],.238,delta=.015)
            self.assertGreater(o['bar_height'],.32) # fragments merged through fish
        self.assertTrue(self.v.bite(crop(self.image('bite'),self.c['bite_roi']))['bite'])
        self.assertFalse(self.v.bite(crop(self.image('control'),self.c['bite_roi']))['bite'])
    def test_blank_not_a_fish(self):
        self.assertFalse(self.v.control(np.zeros((526,63,3),np.uint8))['valid'])
    def test_predictive_braking_and_edges(self):
        controller=self.m.FishingController({**self.c,"control_mode":"bang_bang"})
        o=dict(center=.6,fish=.4,bar_height=.2,bar_top=.5,bar_bottom=.7)
        self.assertTrue(controller.decide(o,0,False)['down'])
        o.update(center=.44,bar_top=.34,bar_bottom=.54)
        self.assertFalse(controller.decide(o,.1,True)['down'])
        controller.reset()
        o.update(center=.2,fish=.5,bar_top=.1,bar_bottom=.3)
        self.assertFalse(controller.decide(o,1,True)['down'])
    def test_loss_does_not_report_success(self):
        p=self.m.FishingProgram(self.c,self.v)
        p.step(dict(valid=True,center=.5,fish=.4,bar_height=.2,bar_top=.4,bar_bottom=.6),0,False)
        self.assertTrue(p.step({'valid':False},.05,True)['down'])
        self.assertFalse(p.step({'valid':False},.2,True)['down'])
        self.assertEqual(p.step({'valid':False},1,True)['stop'],'track_lost_result_pending')
    def test_hook_one_click_transition(self):
        p=self.m.FishingProgram({**self.c,'start_phase':'waiting'},self.v)
        self.assertFalse(p.step({'bite':True},0,False)['down'])
        self.assertTrue(p.step({'bite':True},.02,False)['down'])
        self.assertFalse(p.step({'valid':False},.1,True)['down'])
        self.assertFalse(p.step({'valid':False},.2,False)['down'])
        self.assertEqual(p.step({'valid':False},4,False)['stop'],'hook_transition_unknown')
    def test_input_changes_only_and_cleanup(self):
        b=FakeBackend()
        with ActionComputer(live=True,backend=b) as c:
            latch=InputLatch(c,True)
            latch.set(True,0); latch.set(True,.1); latch.set(False,.11,.2)
            self.assertEqual(len(b.events),1)
            latch.set(False,.12,force=True)
            latch.set(True,.3)
        self.assertEqual(b.events,[('button','left',True),('button','left',False),('button','left',True),('button','left',False)])
    def test_exception_and_cancel_release_input(self):
        class Capture:
            closed=False
            def grab(self,roi): raise RuntimeError('lost focus')
            def close(self): self.closed=True
        for cancel in (False,True):
            b=FakeBackend(); capture=Capture()
            with ActionComputer(live=True,backend=b) as c:
                InputLatch(c,True).set(True,0)
                r=run_loop(capture,self.m.FishingProgram(self.c,self.v),c,self.c,live=True,should_yield=lambda:cancel)
                self.assertFalse(c.buttons)
            self.assertTrue(capture.closed); self.assertEqual(r['outcome'],'unknown')
    def test_loop_telemetry_and_resize_release(self):
        class Program:
            state='control'
            reset_count=0
            def roi(self): return [0,0,1,1]
            def reset_motion(self): self.reset_count+=1
            def detect(self,image): return {'valid':True}
            def step(self,o,t,down): return {'down':True}
        class Capture:
            calls=0
            def grab(self,roi):
                self.calls+=1
                return np.zeros((2,2,3),np.uint8),self.bounds()
            def bounds(self): return (0,0,100 if self.calls==1 else 200,100)
            def close(self): pass
        program=Program(); b=FakeBackend()
        with ActionComputer(live=True,backend=b) as c:
            r=run_loop(Capture(),program,c,{**self.c,'fps':240},live=True)
            self.assertFalse(c.buttons)
        self.assertEqual(r['reason'],'window_resized_recalibrate')
        self.assertEqual(r['frames'],1)
        self.assertEqual(program.reset_count,1)
        self.assertGreater(r['actual_fps'],0)
        self.assertEqual(set(r['timings_mean_ms']),{'capture_ms','recognition_ms','control_ms','input_ms'})
        self.assertEqual(b.events,[('button','left',True),('button','left',False)])
    def test_pwm_hover_pulses_and_speed_feedback(self):
        controller=self.m.FishingController({**self.c,"control_mode":"pwm"})
        o=dict(center=.5,fish=.5,bar_height=.2,bar_top=.4,bar_bottom=.6)
        states=[controller.decide(o,t,False)['down'] for t in (0,.04,.09,.14,.17)]
        self.assertEqual(states,[True,True,False,False,True])
        controller.reset()
        controller.decide(o,0,False)
        falling=controller.decide({**o,'center':.51},.05,True)
        self.assertGreater(falling['duty'],self.c['pwm_hover_duty'])
        self.assertEqual(falling['cycle_duty'],self.c['pwm_hover_duty'])
        controller.reset()
        controller.decide(o,0,False)
        rising=controller.decide({**o,'center':.49},.05,True)
        self.assertLess(rising['duty'],self.c['pwm_hover_duty'])
    def test_pwm_real_latch_has_release_intervals(self):
        controller=self.m.FishingController({**self.c,"control_mode":"pwm"})
        b=FakeBackend()
        o=dict(center=.5,fish=.5,bar_height=.2,bar_top=.4,bar_bottom=.6)
        with ActionComputer(live=True,backend=b) as c:
            latch=InputLatch(c,True)
            for i in range(60):
                t=i/60
                d=controller.decide(o,t,latch.down)
                latch.set(d['down'],t,self.c['minimum_hold'])
        events=[e for e in b.events if e[0]=='button']
        self.assertGreater(len(events),8)
        self.assertTrue(all(events[i][2]!=events[i-1][2] for i in range(1,len(events))))
    def test_pwm_invalid_fast_period_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'
            p.write_text(json.dumps({**self.c,'control_mode':'pwm','pwm_period_seconds':.02}))
            with self.assertRaises(ValueError): load(ROOT,p)
    def test_inertia_brakes_before_fish_is_crossed(self):
        c={**self.c,'control_mode':'bang_bang','inertia_braking':True}
        ctrl=self.m.FishingController(c)
        o=dict(center=.56,fish=.5,bar_height=.3,bar_top=.41,bar_bottom=.71)
        ctrl.decide(o,0,True)
        # Still below fish, but rising quickly: release before crossing it.
        d=ctrl.decide({**o,'center':.52,'bar_top':.37,'bar_bottom':.67},.05,True)
        self.assertFalse(d['down']); self.assertTrue(d['braking'])
        ctrl.reset()
        o.update(center=.44,bar_top=.29,bar_bottom=.59)
        ctrl.decide(o,0,False)
        # Still above fish, but falling quickly: hold to brake descent.
        d=ctrl.decide({**o,'center':.48,'bar_top':.33,'bar_bottom':.63},.05,False)
        self.assertTrue(d['down']); self.assertTrue(d['braking'])
    def test_inertia_reduces_oscillation_in_synthetic_physics(self):
        def simulate(enabled):
            ctrl=self.m.FishingController({**self.c,'control_mode':'bang_bang','inertia_braking':enabled})
            y,v,down,changed=.7,0,False,-1
            errors=[]
            for i in range(900):
                t=i/60
                o=dict(center=y,fish=.5,bar_height=.2,bar_top=y-.1,bar_bottom=y+.1)
                request=ctrl.decide(o,t,down)['down']
                if request!=down and t-changed>=self.c['minimum_hold']: down=request; changed=t
                v+=(-2 if down else 1)/60; y+=v/60
                if y<.1: y=.1; v=abs(v)*.5
                if y>.9: y=.9; v=-abs(v)*.5
                if i>180: errors.append(abs(y-.5))
            return sum(errors)/len(errors),max(errors)
        old_mean,old_peak=simulate(False); new_mean,new_peak=simulate(True)
        self.assertLess(new_mean,old_mean*.7)
        self.assertLess(new_peak,old_peak*.7)
    def test_inertia_settings_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'
            p.write_text(json.dumps({**self.c,'approach_seconds':0}))
            with self.assertRaises(ValueError): load(ROOT,p)
    def test_bad_config_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'; p.write_text(json.dumps({**self.c,'fps':0}))
            with self.assertRaises(ValueError): load(ROOT,p)

if __name__=='__main__': unittest.main()
