import unittest
import numpy as np
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate,TimedPlaybackBank

def template(key='a',offset=0,period=1):
 x=np.linspace(.25,.8,12)
 return TimedRopeTemplate(dict(template_id=key,stage=2,state='normal',direction='reverse',camera_id='test',period_seconds=period,samples=[dict(elapsed_cycle_fraction=float(u),points=np.column_stack([x,.5+offset+.12*np.sin(2*np.pi*u)+.2*(x-.5)*np.cos(2*np.pi*u)]).tolist()) for u in np.linspace(0,1,33)]))
def points(t,u):
 x=np.linspace(.26,.79,12);return np.column_stack([x,t.curve(u,x)])
class TimedPlaybackTests(unittest.TestCase):
 def test_cycle_wrap_and_unknown_support(self):
  t=template();np.testing.assert_allclose(t.curve(.25,[.4]),t.curve(1.25,[.4]));self.assertTrue(np.isnan(t.curve(.2,[.1])[0]))
 def test_small_error_is_limited_gentle(self):
  t=template();b=TimedPlaybackBank([t]);b.start=.025;r=b.update(0,points(t,0),trusted=True);self.assertEqual(r['path'],'gentle');self.assertLessEqual(abs(r['phase_correction']),.01)
 def test_large_error_needs_window_then_recovers(self):
  t=template();b=TimedPlaybackBank([t]);b.start=.2;paths=[]
  for at in [0,.05,.10,.15,.20]:paths.append(b.update(at,points(t,at),trusted=True)['path'])
  self.assertEqual(paths[0],'collecting_recovery');self.assertIn('recovery',paths);self.assertLess(abs(b.start),.01)
 def test_occlusion_only_predicts(self):
  t=template();b=TimedPlaybackBank([t]);b.start=0;r=b.update(.4,points(t,.8),trusted=False);self.assertEqual(r['path'],'predict_only');self.assertEqual(b.start,0)
 def test_candidate_switch_preserves_alternatives(self):
  a=template('wrong',.15);c=template('right');b=TimedPlaybackBank([a,c]);b.start=0
  for at in [0,.05,.1,.15,.2]:b.update(at,points(c,at),trusted=True)
  self.assertEqual(b.selected.key,'right');self.assertEqual(len(b.templates),2)
 def test_nonmonotonic_time_rejected(self):
  b=TimedPlaybackBank([template()]);b.update(1)
  with self.assertRaises(ValueError):b.update(1)
if __name__=='__main__':unittest.main()
