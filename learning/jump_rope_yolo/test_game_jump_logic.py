"""Timing behavior checks using known synthetic cycle geometry; no game input."""
import json
from pathlib import Path
import unittest
import cv2
import numpy as np
from game_jump_logic import JumpClock

class ClockTests(unittest.TestCase):
    def make_clock(self):
        c=json.loads((Path(__file__).parent/'game_jump_config.json').read_text());c['stage']=1
        return JumpClock(c)
    def test_known_cycle_missing_frames_and_trigger_timing(self):
        clock=self.make_clock();template=clock.templates[0];events=[];rows=[]
        for i in range(240):
            now=i/60;phase=(.05+now/template.period)%1
            mask=np.zeros((540,880),np.uint8);x=np.linspace(.25,.81,200);y=template.curve(phase,x);ok=np.isfinite(y)
            points=np.column_stack([x[ok]*1280-240,y[ok]*720]).round().astype(np.int32)
            if len(points)>1:cv2.polylines(mask,[points],False,255,6)
            if 100<=i<104 or 180<=i<210:mask[:]=0
            r=clock.update(now,mask>0,(720,1280,3),(240,0,1120,540));rows.append(r)
            if r['trigger']:events.append(now);clock.on_trigger(now)
        self.assertEqual(rows[103]['status'],'predicting')
        self.assertEqual(rows[209]['status'],'lost')
        self.assertGreaterEqual(len(events),2)
        for at in events:
            error=min(abs(((.05+at/template.period-target+.5)%1-.5)*template.period) for target in template.data['jump_progress_nodes'])
            self.assertLess(error,.055,'Synthetic trigger must stay near known calibrated onset')
    def test_valid_onset_can_trigger_immediately_and_repeat_within_300ms(self):
        clock=self.make_clock();template=clock.templates[0]
        target=template.data['jump_progress_nodes'][0]
        def mask_at(phase):
            mask=np.zeros((540,880),np.uint8);x=np.linspace(.25,.81,200)
            y=template.curve(phase,x);ok=np.isfinite(y)
            points=np.column_stack([x[ok]*1280-240,y[ok]*720]).round().astype(np.int32)
            cv2.polylines(mask,[points],False,255,6)
            return mask>0
        first=clock.update(0,mask_at(target),(720,1280,3),(240,0,1120,540))
        self.assertTrue(first['trigger'],'First valid onset must not wait 150ms')
        clock.on_trigger(0)
        repeated=clock.update(.02,mask_at((target+.02/template.period)%1),(720,1280,3),(240,0,1120,540))
        self.assertTrue(repeated['trigger'],'Repeated onset must not be blocked for 300ms')

    def test_no_observation_cannot_initialize(self):
        clock=self.make_clock();mask=np.zeros((540,880),bool)
        for i in range(30):self.assertFalse(clock.update(i/60,mask,(720,1280,3),(240,0,1120,540))['trigger'])
    def test_unsupported_stage_does_not_guess(self):
        clock=self.make_clock();clock.set_stage(6)
        r=clock.update(0,np.zeros((540,880),bool),(720,1280,3),(240,0,1120,540))
        self.assertEqual(r['status'],'unsupported_stage');self.assertFalse(r['trigger'])


class StageFiveTests(unittest.TestCase):
    def config(self):
        return json.loads((Path(__file__).parent/'game_jump_config.json').read_text(encoding='utf-8'))

    def test_stage5_keeps_original_bank_and_marks_trial(self):
        from game_jump_logic import ROOT
        c=self.config()
        current=json.loads((ROOT/c['catalog']).read_text(encoding='utf-8'))
        original=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_template_library/generated/stages_1_4_timed/catalog.json').read_text(encoding='utf-8'))
        self.assertEqual([e for e in current['templates'] if e['stage']<5],original['templates'])
        added=[e for e in current['templates'] if e['stage']==5]
        self.assertEqual(len(added),7)
        for e in added:
            self.assertFalse(json.loads((ROOT/e['file']).read_text(encoding='utf-8'))['verified'])

    def test_stage4_to_5_resets_and_requires_new_observation(self):
        c=self.config();c['stage']=0
        clock=JumpClock(c);clock.set_stage(4)
        clock.last_seen=0.;clock.phase=.5;clock.selected=0
        clock.set_stage(5)
        self.assertIsNone(clock.selected);self.assertIsNone(clock.last_seen)
        for i in range(30):
            r=clock.update(i/60,np.zeros((540,880),bool),(720,1280,3),(240,0,1120,540))
            self.assertNotEqual(r['status'],'unsupported_stage');self.assertFalse(r['trigger'])

    def test_stage5_modes_can_track_and_request_at_onsets(self):
        c=self.config();c['stage']=5
        templates=JumpClock(c).templates
        for template in templates:
            with self.subTest(template=template.key):
                clock=JumpClock(c);events=[]
                for i in range(240):
                    now=i/60;phase=(.05+now/template.period)%1
                    mask=np.zeros((540,880),np.uint8)
                    x=np.linspace(.25,.81,200);y=template.curve(phase,x);ok=np.isfinite(y)
                    points=np.column_stack([x[ok]*1280-240,y[ok]*720]).round().astype(np.int32)
                    if len(points)>1:cv2.polylines(mask,[points],False,255,6)
                    r=clock.update(now,mask>0,(720,1280,3),(240,0,1120,540))
                    self.assertNotEqual(r['status'],'unsupported_stage')
                    if r['trigger']:events.append(now);clock.on_trigger(now)
                self.assertGreaterEqual(len(events),2)
        

class DirectionalLowSwingTests(unittest.TestCase):
    def clock(self):
        c=json.loads((Path(__file__).parent/'game_jump_config.json').read_text(encoding='utf-8'));c['stage']=0
        return JumpClock(c)
    def test_manual_sorted_stage3_onsets_keep_correct_physical_direction(self):
        clock=self.clock();t=next(t for t in clock.templates if t.context[:2]==(3,'low_swing'))
        windows=clock.onset_windows(t)
        self.assertEqual(windows[0]['direction'],'front_to_back')
        self.assertEqual(windows[1]['direction'],'back_to_front')
        self.assertEqual(windows[0]['extra_early_seconds'],0)
        self.assertAlmostEqual(windows[1]['extra_early_seconds'],0.)
        self.assertAlmostEqual(windows[1]['phase'],.7705)
        self.assertAlmostEqual(windows[0]['phase'],.2981181391370996)
    def test_directional_windows_stage3_restored_stage4_50ms(self):
        clock=self.clock()
        for t in clock.templates:
            for onset in clock.onset_windows(t):
                extra=onset['extra_early_seconds']
                affected=t.context[0] in (3,4) and t.context[1]=='low_swing' and onset['direction']=='back_to_front'
                self.assertAlmostEqual(extra,(0. if t.context[0]==3 else .05) if affected else (.05 if t.context[0]==5 else 0.))
                # 100ms before the reference lies inside the expanded window only.
                phase=(onset['phase']-.1/t.period)%1
                decision=clock.onset_decision(t,phase)
                self.assertFalse(decision['due'])
    def test_stage4_low_swing_only_gets_relaxed_tracking(self):
        clock=self.clock();clock.set_stage(4)
        for i,t in enumerate(clock.templates):
            if t.context[0]!=4:continue
            clock.selected=i
            settings=clock.matching_settings()
            self.assertEqual(settings['max_predict_seconds'],.4 if t.context[1]=='low_swing' else .25)
            self.assertEqual(settings['minimum_columns'],10 if t.context[1]=='low_swing' else 13)

    def test_stage5_early_window_preserves_late_end(self):
        clock=self.clock()
        for t in clock.templates:
            if t.context[0]!=5:continue
            for onset in clock.onset_windows(t):
                for seconds in (.08,.04,0,-.02):
                    self.assertTrue(clock.onset_decision(t,(onset['phase']-seconds/t.period)%1)['due'])
                self.assertFalse(clock.onset_decision(t,(onset['phase']-.10/t.period)%1)['due'])

    def test_earlier_window_preserves_original_and_late_onset(self):
        clock=self.clock()
        for stage in (3,4):
            t=next(t for t in clock.templates if t.context[:2]==(stage,'low_swing'))
            onset=next(w for w in clock.onset_windows(t) if w['direction']=='back_to_front')
            early=.03 if stage==3 else .08
            for seconds in (early,.02,0,-.02):
                result=clock.onset_decision(t,(onset['phase']-seconds/t.period)%1)
                self.assertTrue(result['due'])
            outside=.05 if stage==3 else .10
            self.assertFalse(clock.onset_decision(t,(onset['phase']-outside/t.period)%1)['due'])

if __name__=='__main__':unittest.main()
