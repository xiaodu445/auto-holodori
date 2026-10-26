import ctypes as C
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.realtime import record_kitchen as recorder


class KitchenRecordingTests(unittest.TestCase):
    def test_mouse_coordinates_and_edges(self):
        stop=threading.Event()
        class API:
            step=0
            def GetForegroundWindow(self):return 7
            def GetClientRect(self,h,p):
                p._obj.right=400;p._obj.bottom=200;return 1
            def ClientToScreen(self,h,p):
                p._obj.x=100;p._obj.y=50;return 1
            def GetCursorPos(self,p):
                p._obj.x=200;p._obj.y=100;return 1
            def GetAsyncKeyState(self,key):
                if key==123:return 0x8000 if self.step>=3 else 0
                if key==1:return 0x8000 if self.step==1 else 0
                self.step+=1;return 0
        events=[]
        recorder.monitor_mouse(API(),7,stop,events,0)
        edges=[e for e in events if e['type']=='mouse_down']
        self.assertEqual(len(edges),1)
        self.assertEqual(edges[0]['client_xy'],[100,50])
        self.assertEqual(edges[0]['client_uv'],[.25,.25])
        self.assertTrue(edges[0]['inside_client'])
        self.assertEqual(events[-1]['type'],'manual_stop')
        self.assertTrue(stop.is_set())

    def test_focus_loss_stops_without_reading_mouse(self):
        class API:
            def GetClientRect(self,h,p):return 1
            def ClientToScreen(self,h,p):return 1
            def GetForegroundWindow(self):return 8
        events=[];stop=threading.Event()
        recorder.monitor_mouse(API(),7,stop,events,0)
        self.assertEqual(events[0]['type'],'focus_lost')
        self.assertTrue(stop.is_set())

    def test_video_timestamps_and_resource_cleanup(self):
        class Capture:
            api=object();closed=False
            def __init__(self,h):pass
            def grab(self,roi):return np.zeros((32,48,3),dtype=np.uint8),(100,50,48,32)
            def close(self):Capture.closed=True
        with tempfile.TemporaryDirectory() as root,patch.object(recorder,'WindowCapture',Capture),patch.object(recorder,'monitor_mouse'):
            output=Path(root)/'recording'
            result=recorder.record(7,output,duration=.1,fps=60)
            rows=json.loads((output/'timestamps.json').read_text())
            self.assertGreater(len(rows),0)
            self.assertEqual(result['frames_encoded'],len(rows))
            self.assertEqual([r['video_index'] for r in rows],list(range(len(rows))))
            self.assertEqual(result['video_size'],(48,32))
            self.assertFalse(result['sends_input'])
            self.assertTrue(Capture.closed)
            self.assertGreater((output/'screen.avi').stat().st_size,0)

    def test_capture_setup_failure_still_writes_summary(self):
        with tempfile.TemporaryDirectory() as root,patch.object(recorder,'WindowCapture',side_effect=RuntimeError('unavailable')):
            result=recorder.record(7,Path(root)/'failed',duration=.1)
            self.assertEqual(result['reason'],'unavailable')
            self.assertTrue((Path(root)/'failed/summary.json').exists())

    def test_invalid_settings_do_not_create_capture(self):
        with patch.object(recorder,'WindowCapture') as capture:
            with self.assertRaises(ValueError):recorder.record(7,'unused',fps=0)
            capture.assert_not_called()
