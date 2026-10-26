import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
import threading
import wave
import json
from modular_agent.realtime.loopback_audio import LoopbackAudio,block_timing
class AudioTests(unittest.TestCase):
 def test_adc_times_share_monotonic_origin(self):
  r=block_timing(dict(input_buffer_adc_time=40.,current_time=40.02),100.,480,48000,90.)
  self.assertAlmostEqual(r['t'],9.98);self.assertEqual(r['timestamp_source'],'portaudio_adc_to_perf_counter')
 def test_missing_driver_timestamp_is_marked_estimate(self):
  r=block_timing(dict(input_buffer_adc_time=0.,current_time=0.),100.,480,48000,90.)
  self.assertAlmostEqual(r['t'],9.99);self.assertEqual(r['timestamp_source'],'callback_duration_estimate')
 def test_callback_writer_preserves_pcm_and_sample_indices(self):
  b=LoopbackAudio.__new__(LoopbackAudio);b.pa=Mock(paInt16=8,paAbort=2,paContinue=0);b.host=Mock();b.stream=None;b.worker=None;b.errors=[];b.blocks=0;b.frames=0;b.peak=0;b.first_t=None;b.last_t=None;b.status_blocks=0;b.estimated_blocks=0;b.rate=48000;b.channels=2;b.device=dict(index=10,name='fake loopback')
  with tempfile.TemporaryDirectory() as d:
   b.start(d,0.,threading.Event());callback=b.host.open.call_args.kwargs['stream_callback'];data=b'\x01\x00\x02\x00'*8
   callback(data,8,dict(input_buffer_adc_time=1.,current_time=1.01),0);callback(data,8,dict(input_buffer_adc_time=1.02,current_time=1.03),1);b.close()
   with wave.open(str(Path(d)/'audio.wav')) as w:self.assertEqual(w.getnframes(),16);self.assertEqual(w.getnchannels(),2);self.assertEqual(w.readframes(16),data*2)
   rows=[json.loads(s) for s in (Path(d)/'audio-timestamps.jsonl').read_text().splitlines()];self.assertEqual([r['sample_start'] for r in rows],[0,8]);self.assertEqual(b.status_blocks,1);self.assertFalse(b.errors)
   b.host.terminate.assert_called_once();b.stream=None
