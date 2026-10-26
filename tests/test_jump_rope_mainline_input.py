import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.realtime.jump_rope_mainline import MainlineController,AudioPolicy,MainlineVision
from modular_agent.realtime.trajectory_bank import Playback,AngularWarp
from modular_agent.realtime.jump_rope_start_gate import GoStartGate
import cv2
from modular_agent.realtime.keyboard import run_key_loop

TIMING=json.loads(Path('domains/hololive_dreams/models/jump_rope/jump_rope_mainline_input_config.json').read_text(encoding='utf-8-sig'))

class MainlineInputTests(unittest.TestCase):
    def setUp(self):
        self.p=Playback(1,'rotation_forward',.73,1.,1)
        self.bank=SimpleNamespace(items=[self.p],active=1,boundary=.875,warp=AngularWarp())
        self.c=dict(max_frame_age=.045,max_observation_gap=.08)
        self.controller=MainlineController(self.c,self.bank,TIMING)
        self.o=dict(model_exists=True,whole_curve=[[.5,.2],[.6,.4]],motion_state='rotation_forward',start_gate=dict(playing=True),avatar_valid=True,avatar_y=.36,avatar_ground_y=.36,phase_estimate=dict(locked=True,confidence=.8))
    def ready(self):
        for t in (1.,1.016,1.032):d=self.controller.step(self.o,t)
        return d
    def test_request_only_commits_after_dispatch(self):
        self.assertTrue(self.ready()['down']);self.assertEqual(self.controller.jumps,0)
        self.controller.on_input(1.032,True);self.assertEqual(self.controller.jumps,1)
        self.assertFalse(self.controller.step(self.o,1.048)['down'])
    def test_invisible_avatar_does_not_inhibit_timed_jump(self):
        self.o['avatar_valid']=False;self.o['avatar_y']=None
        self.assertTrue(self.ready()['down'])
    def test_duplicate_interval_then_next_template_pass(self):
        self.ready();self.controller.on_input(1.032,True)
        self.assertFalse(self.controller.step(self.o,1.048)['down'])
        for t in np.arange(1.064,1.35,.016):
            self.p.phase=.4;self.controller.step(self.o,float(t))
        self.p.phase=1.73
        self.assertTrue(self.controller.step(self.o,1.352)['down'])
    def test_prestart_and_no_displayed_curve_never_press(self):
        self.o['start_gate']['playing']=False;self.assertFalse(self.ready()['down'])
        self.o['start_gate']['playing']=True;self.o['whole_curve']=[]
        self.assertFalse(self.ready()['down'])
    def test_low_confidence_unlocked_display_still_drives_input(self):
        self.o['phase_estimate'].update(locked=False,confidence=0.)
        self.o['scene_changed']=True
        self.assertTrue(self.ready()['down'])
    def test_just_crossed_onset_is_not_wrapped_to_next_cycle(self):
        self.p.phase=.75;self.assertTrue(self.ready()['down'])
        self.p.phase=.80;self.assertFalse(self.controller.step(self.o,1.048)['down'])
    def test_reverse_late_onset(self):
        self.p.mode='rotation_reverse';self.p.phase=.24;self.o['motion_state']=self.p.mode
        self.assertTrue(self.ready()['down'])
    def test_processing_delay_extrapolates_same_clock(self):
        self.p.phase=.69
        d=self.controller.step(self.o,1.,frame_age=.06)
        self.assertTrue(d['down']);self.assertAlmostEqual(d['prediction']['eta'],-.01)
    def test_frame_gap_does_not_inhibit_current_prediction(self):
        self.p.phase=.4;self.controller.step(self.o,1.)
        self.p.phase=.73;self.assertTrue(self.controller.step(self.o,1.2)['down'])
    def test_reverse_uses_signed_clock(self):
        self.p.mode='rotation_reverse';self.p.phase=.26;self.o['motion_state']=self.p.mode
        self.assertTrue(self.ready()['down'])
    def test_occlusion_uses_acquired_clock(self):
        self.o['rope_valid']=False;self.assertTrue(self.ready()['down'])
    def test_audio_failure_does_not_block_displayed_prediction(self):
        self.o['audio_error']=['unavailable'];self.assertTrue(self.ready()['down'])
    def test_roi_go_gate_matches_full_frame(self):
        roi=[.01,.02,.88,.72];full=np.zeros((360,640,3),np.uint8);go=full.copy()
        cv2.rectangle(go,(280,130),(355,165),(0,255,255),-1)
        a=GoStartGate();b=GoStartGate(roi=roi)
        for now,im in enumerate([go]*3+[full]*3):
            l,t,r,z=roi;local=im[round(t*360):round(z*360),round(l*640):round(r*640)]
            self.assertEqual(a.update(im,now),b.update(local,now))
        self.assertEqual(a.started_at,b.started_at)
    def test_audio_bias_is_temporary_and_low_needs_causal_cue(self):
        low=Playback(2,'low_swing',0.,.4,0,score=.9);self.p.score=.5
        bank=SimpleNamespace(items=[self.p,low],active=1,c=dict(confirmation_seconds=.065),role=lambda p:'normal')
        seen=[]
        bank.choose=lambda *a,**kw:seen.append(low.score)
        policy=AudioPolicy(bank,dict(hint_seconds=3.,soft_score_bonus=.05))
        policy.choose(10,.016);self.assertEqual(seen[-1],-1.);self.assertEqual(low.score,.9)
        policy.prefix=dict(time=10.01,motion_hint='low_swing',distance=.05,margin=.2)
        policy.choose(10,.016);self.assertEqual(seen[-1],-1.)
        policy.prefix['time']=9.9;policy.choose(10,.016);self.assertEqual(seen[-1],.9)
        policy.choose(10.4,.016);self.assertEqual(seen[-1],-1.)
    def test_pulse_release_before_next_slow_recognition(self):
        clock=SimpleNamespace(t=0.)
        calls=[]
        computer=SimpleNamespace(live=False,keys=set(),buttons=set(),stopped=False,release_all=lambda:calls.append('release_all'))
        capture=SimpleNamespace(grab=lambda roi:(np.zeros((4,4,3),np.uint8),(0,0,4,4)),bounds=lambda:(0,0,4,4),close=lambda:None)
        controller=SimpleNamespace(state='grounded',mode='rotation',jumps=0,crossings=0,step=lambda *a,**kw:dict(down=True))
        c=dict(timeout=.02,roi=[0,0,1,1],analysis_width=4,fps=60,max_frame_age=.045,pulse_seconds=.035,synchronous_space_pulse=True)
        def sleep(x):clock.t+=x
        with patch('modular_agent.realtime.keyboard.time.perf_counter',lambda:clock.t),patch('modular_agent.realtime.keyboard.time.sleep',sleep):
            result=run_key_loop(capture,SimpleNamespace(detect=lambda *a,**kw:{}),controller,computer,c)
        events=result['input_events'];self.assertEqual([e['down'] for e in events],[True,False])
        self.assertAlmostEqual(events[1]['started']-events[0]['dispatched'],.035,places=5)
        self.assertIn('release_all',calls)
    def test_loop_does_not_override_trusted_prediction_for_delay(self):
        for trusted in (False,True):
            clock=SimpleNamespace(t=0.)
            def detect(*args,**kwargs):clock.t+=.06;return {}
            computer=SimpleNamespace(live=False,keys=set(),buttons=set(),stopped=False,release_all=lambda:None)
            capture=SimpleNamespace(grab=lambda roi:(np.zeros((4,4,3),np.uint8),(0,0,4,4)),bounds=lambda:(0,0,4,4),close=lambda:None)
            controller=SimpleNamespace(state='tracking',mode='rotation',jumps=0,crossings=0,step=lambda *a,**kw:dict(down=True))
            c=dict(timeout=.02,roi=[0,0,1,1],analysis_width=4,fps=60,max_frame_age=.045,pulse_seconds=.035,synchronous_space_pulse=True,mainline_trust_prediction=trusted)
            def sleep(x):clock.t+=x
            with patch('modular_agent.realtime.keyboard.time.perf_counter',lambda:clock.t),patch('modular_agent.realtime.keyboard.time.sleep',sleep):
                result=run_key_loop(capture,SimpleNamespace(detect=detect),controller,computer,c)
            self.assertEqual(len(result['input_events']),2 if trusted else 0)
    def test_focus_exception_releases_held_pulse(self):
        clock=SimpleNamespace(t=0.);count=SimpleNamespace(n=0)
        def bounds():
            count.n+=1
            if count.n>1:raise RuntimeError('unfocused')
            return (0,0,4,4)
        computer=SimpleNamespace(live=False,keys=set(),buttons=set(),stopped=False,release_all=lambda:None)
        capture=SimpleNamespace(grab=lambda roi:(np.zeros((4,4,3),np.uint8),(0,0,4,4)),bounds=bounds,close=lambda:None)
        controller=SimpleNamespace(state='grounded',mode='rotation',jumps=0,crossings=0,step=lambda *a,**kw:dict(down=True))
        c=dict(timeout=.02,roi=[0,0,1,1],analysis_width=4,fps=60,max_frame_age=.045,pulse_seconds=.035,synchronous_space_pulse=True)
        with patch('modular_agent.realtime.keyboard.time.perf_counter',lambda:clock.t):
            result=run_key_loop(capture,SimpleNamespace(detect=lambda *a,**kw:{}),controller,computer,c)
        self.assertIn('unfocused',result['reason']);self.assertEqual([e['down'] for e in result['input_events']],[True,False])

if __name__=='__main__':unittest.main()
