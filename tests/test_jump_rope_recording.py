import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from modular_agent.realtime import record_jump_rope as recorder

class RecordingTests(unittest.TestCase):
    def test_space_edges_are_timestamped_without_repeat_edges(self):
        class API:
            index=0
            def GetForegroundWindow(self):return 7
            def GetAsyncKeyState(self,key):
                if key==32:
                    values=[False,True,True,False]
                    value=values[min(self.index,3)];self.index+=1
                    return 0x8000 if value else 0
                return 0x8000 if self.index>=4 else 0
        events=[];stop=threading.Event()
        recorder.monitor_space(API(),7,stop,events,0)
        self.assertEqual([e['type'] for e in events],['initial_state','key_down','key_up','manual_stop'])
        self.assertEqual(sorted(e['t'] for e in events),[e['t'] for e in events])
    def test_encoder_queue_discards_oldest(self):
        items=queue.Queue(maxsize=2);items.put(1);items.put(2)
        self.assertEqual(recorder.offer_latest(items,3),1)
        self.assertEqual([items.get(),items.get()],[2,3])
    def test_video_frames_and_timestamp_file_align_and_capture_closes(self):
        class Capture:
            api=object();closed=False
            def __init__(self,handle):pass
            def grab(self,roi):return np.zeros((32,48,3),dtype=np.uint8),(0,0,48,32)
            def close(self):Capture.closed=True
        with tempfile.TemporaryDirectory() as root,patch.object(recorder,'WindowCapture',Capture),patch.object(recorder,'monitor_space',return_value=None):
            result=recorder.record(7,Path(root)/'recording',duration=.2,fps=120,width=48)
            rows=json.loads((Path(root)/'recording/timestamps.json').read_text())
            self.assertGreater(len(rows),0)
            self.assertEqual(result['frames_encoded'],len(rows))
            self.assertEqual([r['video_index'] for r in rows],list(range(len(rows))))
            self.assertTrue(Capture.closed)
            self.assertFalse(result['sends_input'])
            self.assertTrue((Path(root)/'recording/screen.avi').stat().st_size>0)
