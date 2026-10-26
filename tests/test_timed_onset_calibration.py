import json,tempfile,unittest
from pathlib import Path
import numpy as np
from modular_agent.realtime.timed_onset_calibration import circle_median,calibrate_data,transfer_onsets
class OnsetTests(unittest.TestCase):
 def test_wrap_and_outlier(self):
  u,n,_=circle_median([.98,.99,.01,.02,.45]);self.assertLess(abs((u+.5)%1-.5),.025);self.assertEqual(n,4)
 def test_low_has_two_independent_onsets(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);rec=root/'rec';rec.mkdir();(rec/'timestamps.json').write_text(json.dumps([{'t':0},{'t':4}]))
   edges=[dict(t=t,type='key_down',key='space',focused=True) for t in [.1,.6,1.11,1.59,2.12,2.61]];edges.append(dict(t=3.9,type='key_down',key='space',focused=False));(rec/'inputs.json').write_text(json.dumps(edges))
   d=calibrate_data(dict(source_recording='rec',source_interval=dict(start_frame=0,end_frame_exclusive=1),training_time_range=dict(start=0),period_seconds=1,state='low_swing',jump_progress_nodes=[.2,.8]),root)
   self.assertTrue(np.allclose(d['jump_progress_nodes'],[.11,.6],atol=.015));self.assertFalse(d['manual_onset_calibration']['short_pulse_verified'])
 def test_pose_transfer_uses_target_clock(self):
  def make(key,offset):
   x=np.linspace(.25,.8,20)
   return dict(template_id=key,stage=2,state='normal',direction='forward',camera_id='test',period_seconds=1,jump_progress_nodes=[.3],samples=[dict(elapsed_cycle_fraction=float(u),points=np.column_stack([x,.5+.1*np.sin(2*np.pi*(u+offset))+.2*(x-.5)*np.cos(2*np.pi*(u+offset))]).tolist()) for u in np.linspace(0,1,65)])
  d=transfer_onsets(make('target',.2),make('source',0));self.assertAlmostEqual(d['jump_progress_nodes'][0],.1,delta=.003)
