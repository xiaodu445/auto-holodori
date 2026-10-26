"""Failure detection and archive tests using synthetic counters/frames; no game input."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from failure_capture import CounterStallDetector, FailureRecorder


def glyph(value):
    g=np.zeros((48,40),bool)
    left=2+(value%8)*4
    g[5:43,left:left+3]=True
    return [g]


def sample(detector, start, stop, value, reading=None, visible=True):
    events=[]
    for t in np.arange(start,stop,.05):
        row=detector.update(float(t),glyph(value) if visible else [],reading)
        if row['trigger']:events.append(row['trigger'])
    return events


class StallTests(unittest.TestCase):
    def detector(self):return CounterStallDetector(dict(stall_seconds=2,counter_stable_seconds=.1,minimum_progress_changes=2))
    def progressed(self,d):
        events=[]
        for value in range(3):events+=sample(d,value*.5,(value+1)*.5,value,value)
        return events
    def test_static_startup_does_not_trigger(self):
        d=self.detector();self.assertEqual(sample(d,0,10,0,0),[])
    def test_missing_digit_references_do_not_freeze_progress(self):
        d=self.detector();events=[]
        for value in range(20):events+=sample(d,value*.5,(value+1)*.5,value,None)
        self.assertEqual(events,[]);self.assertGreater(d.changes,2)
    def test_stall_emits_once_and_rearms_after_progress(self):
        d=self.detector();self.assertEqual(self.progressed(d),[])
        events=sample(d,1.5,8,2,2)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['reason'],'counter_stalled')
        self.assertGreaterEqual(events[0]['stagnant_seconds'],2)
        self.assertLessEqual(events[0]['stagnant_seconds'],2.051)
        self.assertEqual(sample(d,8,8.5,3,3),[])
        self.assertEqual(sample(d,8.5,9,4,4),[])
        self.assertEqual(len(sample(d,9,13,4,4)),1)
    def test_counter_disappearance_is_labeled_uncertain(self):
        d=self.detector();self.progressed(d)
        events=sample(d,1.5,6,2,None,visible=False)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['reason'],'counter_unreadable_after_progress')
        self.assertEqual(events[0]['classification'],'suspected_death')
    def test_pause_or_capture_gap_requires_new_progress(self):
        d=self.detector();self.progressed(d)
        self.assertEqual(sample(d,10,15,2,2),[])
    def test_same_numeric_count_animation_does_not_refresh_progress(self):
        d=self.detector();self.progressed(d);events=[]
        for index in range(12):events+=sample(d,1.5+index*.4,1.5+(index+1)*.4,2+index%2,2)
        self.assertEqual(len(events),1)
    def test_counter_reset_does_not_carry_old_progress(self):
        d=self.detector();self.progressed(d)
        self.assertEqual(sample(d,1.5,6,0,0),[])
    def test_three_digit_counter_roi_and_complete_reference(self):
        from game_jump_live import StageHint
        hint=StageHint();image=np.zeros((720,1280,3),np.uint8)
        for i in range(3):
            digit=cv2.resize(np.uint8(hint.refs['9'][0])*255,(80,96),interpolation=cv2.INTER_NEAREST)
            image[55:151,48+i*70:128+i*70]=digit[:,:,None]
        hint.update(image,0)
        self.assertEqual(len(hint.glyphs),3);self.assertEqual(hint.count_reading,999)
    def test_known_numeric_change_survives_changing_glyph_animation(self):
        d=self.detector();events=[]
        for value in range(8):
            for frame in range(10):
                row=d.update(value*.5+frame*.05,glyph(frame%2),value)
                if row['trigger']:events.append(row['trigger'])
        self.assertEqual(events,[]);self.assertEqual(d.reading,7);self.assertGreaterEqual(d.changes,6)

    def test_last_numeric_reading_is_not_reported_as_fresh(self):
        from game_jump_live import StageHint
        hint=StageHint();hint.count=77
        hint.shapes=lambda _:glyph(6)
        hint.refs={'1':[np.zeros((48,40),bool)],'7':[np.zeros((48,40),bool)]}
        hint.update(None,0)
        self.assertIsNone(hint.count_reading);self.assertEqual(hint.count,77)
        self.assertEqual(len(hint.glyphs),1)


class ArchiveTests(unittest.TestCase):
    def settings(self):return dict(pre_seconds=1,stall_seconds=2,fps=15,jpeg_quality=85,max_buffer_mb=8,counter_stable_seconds=.1,minimum_progress_changes=2)
    def row(self,i):return dict(frame=i,time=i*.1,roi=[80,0,300,120],requested=i==10,sent=i==10,decision=dict(status='observed',phase=.5,eta=.1),count_reading=None)
    def feed(self,recorder,stop=60):
        for i in range(stop):
            image=np.zeros((180,320,3),np.uint8);image[:,i%300:i%300+10]=(30,120,240)
            mask=np.zeros((120,220),bool);mask[50:53,:]=True
            value=min(2,i//5)
            if i==10:recorder.record_input(dict(time=.99,type='key_down',key='space',down=True))
            if i==11:recorder.record_input(dict(time=1.025,type='key_up',key='space',down=False))
            recorder.observe(image,mask,self.row(i),glyph(value),None)
            time.sleep(.002)
    def test_only_failure_tail_is_saved_with_video_masks_events_and_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'failure-clips'
            r=FailureRecorder(root,self.settings(),dict(config={'confidence':.03},run='synthetic'))
            try:
                for i in range(3):
                    r.observe(np.zeros((180,320,3),np.uint8),np.zeros((120,220),bool),self.row(i),glyph(0),None)
                self.assertFalse(root.exists())
                r.reset();self.feed(r)
            finally:r.close()
            self.assertEqual(r.errors,[]);self.assertEqual(len(r.saved),1)
            folder=Path(r.saved[0]);report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
            frames=json.loads((folder/'frames.json').read_text(encoding='utf-8'))
            events=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines()]
            edges=json.loads((folder/'inputs.json').read_text(encoding='utf-8'))
            self.assertEqual(report['classification'],'suspected_death')
            self.assertGreater(len(frames),10);self.assertEqual(frames[0]['clip_time'],0)
            self.assertGreaterEqual(frames[0]['time'],report['trigger']['anchor_time']-1-.001)
            self.assertLessEqual(frames[-1]['time'],report['trigger']['detected_at'])
            self.assertEqual([e['type'] for e in edges],['key_down','key_up'])
            self.assertTrue(all('failure_capture' in e for e in events))
            self.assertEqual(cv2.imread(str(folder/frames[0]['image'])).shape,(180,320,3))
            self.assertEqual(cv2.imread(str(folder/frames[0]['mask']),0).shape,(120,220))
            cap=cv2.VideoCapture(str(folder/'screen.avi'))
            try:self.assertEqual(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),len(frames))
            finally:cap.release()
            self.assertTrue((root/'index.html').is_file());self.assertTrue((folder/'index.html').is_file())
    def test_manual_only_never_auto_saves_and_f10_keeps_last_three_seconds(self):
        with tempfile.TemporaryDirectory() as temp:
            settings=self.settings();settings.update(auto_detect=False,manual_seconds=3,pre_seconds=3)
            root=Path(temp)/'clips';r=FailureRecorder(root,settings,dict(config={}))
            try:
                self.feed(r,stop=80)
                self.assertFalse(root.exists());self.assertEqual(r.saved,[])
                self.assertEqual(r.events[-1]['failure_capture']['state'],'manual_buffering')
                r.manual_save()
            finally:r.close()
            self.assertEqual(len(r.saved),1)
            folder=Path(r.saved[0]);report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
            frames=json.loads((folder/'frames.json').read_text(encoding='utf-8'))
            self.assertEqual(report['trigger']['reason'],'manual_F10')
            self.assertEqual(report['trigger']['requested_seconds'],3)
            self.assertGreaterEqual(frames[0]['time'],7.9-3-1e-6)
            self.assertLessEqual(frames[-1]['time'],7.9+1e-6)
            self.assertLessEqual(report['duration_seconds'],3)
            self.assertGreater(report['duration_seconds'],2.7)

    def test_manual_mark_works_before_automatic_progress_is_established(self):
        with tempfile.TemporaryDirectory() as temp:
            r=FailureRecorder(Path(temp)/'clips',self.settings(),dict(config={}))
            try:
                for i in range(10):
                    r.observe(np.zeros((180,320,3),np.uint8),np.zeros((120,220),bool),self.row(i),glyph(0),None)
                    time.sleep(.002)
                r.manual_save()
            finally:r.close()
            self.assertEqual(len(r.saved),1)
            report=json.loads((Path(r.saved[0])/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['trigger']['reason'],'manual_F10')


if __name__=='__main__':unittest.main()
