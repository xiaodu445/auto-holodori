import json,unittest
from pathlib import Path
import numpy as np
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate
from modular_agent.realtime.timed_cycle_vision import ImageCyclePlayback
from modular_agent.realtime.jump_rope_mainline import MainlineController

def template(key,period=1,stage=2,state='normal',direction='forward'):
 x=np.linspace(.25,.8,12)
 return TimedRopeTemplate(dict(template_id=key,stage=stage,state=state,direction=direction,camera_id='test',period_seconds=period,samples=[dict(elapsed_cycle_fraction=float(u),points=np.column_stack([x,.5+.12*np.sin(2*np.pi*u)+.2*(x-.5)*np.cos(2*np.pi*u)]).tolist()) for u in np.linspace(0,1,33)]))
def tables(b,templates,progress):
 gap=abs((b.grid-progress+.5)%1-.5);q=.85*np.exp(-(gap/.055)**2)
 return {t.key:dict(q=q.copy(),coverage=np.full(len(q),.75),moving=np.full(len(q),.4),seen=np.ones((len(q),41),bool)) for t in templates}
class ImageCycleTests(unittest.TestCase):
 def test_gentle_and_large_recovery(self):
  t=template('a');b=ImageCyclePlayback([t]);b.select_stage(2,0);b.start=-.02;r=b.update(.01,2,tables(b,[t],.01));self.assertEqual(r['path'],'gentle');self.assertLessEqual(abs(r['phase_correction']),.008)
  b=ImageCyclePlayback([t]);paths=[]
  for now in np.arange(0,.5,.025):paths.append(b.update(float(now),2,tables(b,[t],now+.25))['path'])
  self.assertIn('recovery',paths);self.assertNotEqual(paths[0],'recovery')
 def test_candidate_period_switch(self):
  normal=template('normal',1.3);fast=template('fast',.8,state='accelerate');b=ImageCyclePlayback([normal,fast]);paths=[]
  for now in np.arange(0,1,.025):paths.append(b.update(float(now),2,tables(b,[normal,fast],now/.8))['path'])
  self.assertEqual(b.selected.key,'fast');self.assertIn('switch',paths)
 def test_scene_never_resets_playback_clock(self):
  t=template('a');b=ImageCyclePlayback([t]);b.select_stage(2,0);b.start=-.2;r=b.update(.5,2,tables(b,[t],.8),scene=True);self.assertEqual(r['path'],'predict_only');self.assertEqual(b.start,-.2);self.assertEqual(len(b.history),0)
 def test_low_entry_requires_sound(self):
  n=template('n');low=template('low',state='low_swing',direction='bidirectional');b=ImageCyclePlayback([n,low]);b.select_stage(2,0);b.selected=n
  for now in np.arange(0,.5,.025):
   ts=tables(b,[n,low],now);ts['n']['q']*=.4;r=b.update(float(now),2,ts)
  self.assertEqual(b.selected.key,'n');self.assertEqual(r['path'],'low_entry_needs_audio')
 def test_stage_switch_preserves_shape_with_different_cycle_anchor(self):
  a=template('old',stage=2);raw=dict(a.data);raw.update(template_id='new',stage=3,period_seconds=.9)
  x=np.linspace(.25,.8,12);raw['samples']=[dict(elapsed_cycle_fraction=float(u),points=np.column_stack([x,a.curve(u+.3,x)]).tolist()) for u in np.linspace(0,1,33)]
  c=TimedRopeTemplate(raw);b=ImageCyclePlayback([a,c]);b.select_stage(2,0);b.select_stage(3,.2)
  u=(.2-b.start)/c.period;self.assertLess(np.nanmax(abs(a.curve(.2,x)-c.curve(u,x))),.015)
 def test_short_occlusion_preserves_recovery_evidence(self):
  t=template('a');b=ImageCyclePlayback([t]);paths=[]
  for now in [0,.04,.08,.12,.16]:
   ts=tables(b,[t],now+.25)
   if now==.08:ts['a']['q'][:]=0
   paths.append(b.update(now,2,ts)['path'])
  self.assertIn('recovery',paths)
 def test_authorized_clear_low_entry_is_fast(self):
  n=template('n');low=template('low',state='low_swing',direction='bidirectional');b=ImageCyclePlayback([n,low])
  for now in [0,.02,.04]:
   ts=tables(b,[n,low],now);ts['n']['q']*=.4;b.update(now,2,ts,audio_hint=dict(time=0,motion_hint='low_swing',distance=.1,margin=.2))
  self.assertEqual(b.selected.key,'low')
 def test_shared_shapes_reuse_image_sampling(self):
  from modular_agent.realtime.jump_rope import load,phase_rope_components
  root=Path(__file__).resolve().parents[1];config,module,_=load(root);vision,_=phase_rope_components(root,config,module,gear=True,gear_settings_path='domains/hololive_dreams/models/jump_rope_timed_playback_config.json')
  vision.prepare_stage(4,np.zeros((400,500),np.uint8))
  self.assertLess(len(vision.features.grid),sum(t.context[0]==4 for t in vision.templates)*len(vision.playback.grid))
  ids=vision.lookup['stage4-normal-forward-legacy-timed'];np.testing.assert_array_equal(ids,vision.lookup['stage4-accelerate-forward-legacy-timed'])
  self.assertTrue(np.all(np.isfinite(vision.features.options)))
 def test_circle_cannot_reverse_without_low_swing(self):
  f=template('f');r=template('r',direction='reverse');b=ImageCyclePlayback([f,r])
  for now in np.arange(0,.5,.025):
   ts=tables(b,[f,r],now);ts['f']['q']*=.5;b.update(float(now),2,ts)
  self.assertEqual(b.selected.key,'f')
 def test_strong_slow_fragment_not_rejected_for_zero_motion(self):
  t=template('a');b=ImageCyclePlayback([t]);last=None
  for now in [0,.05,.10,.15,.20]:
   ts=tables(b,[t],now+.25);ts['a']['moving'][:]=0;last=b.update(now,2,ts)
  self.assertTrue(last['trusted'])
 def test_catalog_scope(self):
  root=Path(__file__).resolve().parents[1];cat=json.loads((root/'domains/hololive_dreams/data/jump_rope_template_library/generated/stages_1_4_timed/catalog.json').read_text())
  states={(r['stage'],r['state'],r['direction']) for r in cat['templates']};self.assertEqual(len(states),20);self.assertFalse(any(s==2 and role=='decelerate' for s,role,_ in states));self.assertEqual([x for x in states if x[0]==1],[(1,'normal','forward')]);self.assertFalse(any(s>=5 for s,_,_ in states))
 def test_displayed_template_controls_input_without_legacy_clock(self):
  timing=dict(dispatch_window_seconds=.035,late_window_seconds=.035);c=MainlineController({},object(),timing)
  o=dict(start_gate=dict(playing=True),model_exists=True,whole_curve=[[.3,.4],[.7,.5]],motion_state='rotation_reverse',timed_playback=dict(clock_unwrapped=.74,period_seconds=1.3,jump_progress_nodes=[.75],template='human'))
  r=c.step(o,1);self.assertTrue(r['down']);self.assertAlmostEqual(r['prediction']['eta'],.013);c.on_input(1,True);self.assertFalse(c.step(o,1.01)['down'])
 def test_expired_audio_cannot_shorten_gear_confirmation(self):
  spans=[]
  for age in [0,10]:
   normal=template('normal',1.3);fast=template('fast',.8,state='accelerate');b=ImageCyclePlayback([normal,fast])
   for now in np.arange(0,.6,.025):
    evidence=tables(b,[normal,fast],now/.8);evidence[normal.key]['q']*=.65
    r=b.update(float(now),2,evidence,audio_hint=dict(time=float(now-age),motion_hint='accelerate',distance=.1,margin=.1))
    if r['path']=='switch':spans.append(r['pending_span']);break
  self.assertEqual(len(spans),2);self.assertLess(spans[0],.20);self.assertGreaterEqual(spans[1],.20)
 def test_other_waveform_cannot_inherit_gear_confirmation(self):
  normal=template('normal');a=template('fast-a',state='accelerate');z=template('fast-b',state='accelerate');b=ImageCyclePlayback([normal,a,z]);b.select_stage(2,0)
  b.pending=dict(key=a.key,signature=(a.key,),since=-1,count=99,clock=.1,time=.1)
  evidence=tables(b,[normal,a,z],.15);evidence[normal.key]['q']*=.4;evidence[a.key]['q']*=.6
  r=b.update(.15,2,evidence)
  self.assertEqual(b.selected.key,normal.key);self.assertEqual(r['pending'],z.key);self.assertEqual(r['pending_frames'],1);self.assertEqual(r['pending_span'],0)
 def test_large_arc_handoff_requires_stronger_visible_support(self):
  normal=template('normal');fast=template('fast',state='accelerate');b=ImageCyclePlayback([normal,fast]);b.select_stage(2,0)
  evidence=tables(b,[normal,fast],.75);evidence[normal.key]['q']*=.3;evidence[fast.key]['q']*=.7
  r=b.update(.1,2,evidence)
  self.assertEqual(r['path'],'phase_handoff_needs_visible_support');self.assertTrue(r['large_phase_handoff']);self.assertEqual(b.selected.key,normal.key)
 def test_same_candidate_phase_jump_restarts_its_proof(self):
  normal=template('normal');fast=template('fast',state='accelerate');b=ImageCyclePlayback([normal,fast]);b.select_stage(2,0)
  b.pending=dict(key=fast.key,signature=(fast.key,),since=-1,count=99,clock=.90,time=.075)
  evidence=tables(b,[normal,fast],.10);evidence[normal.key]['q']*=.4
  r=b.update(.10,2,evidence)
  self.assertEqual(b.selected.key,normal.key);self.assertEqual(r['pending_frames'],1);self.assertEqual(r['pending_span'],0)
 def test_small_frame_drift_cannot_accumulate_into_false_phase_proof(self):
  normal=template('normal');fast=template('fast',state='accelerate');b=ImageCyclePlayback([normal,fast]);b.select_stage(2,0)
  b.pending=dict(key=fast.key,signature=(fast.key,),since=0,count=99,clock=.10,origin_clock=.10,time=.175)
  evidence=tables(b,[normal,fast],.10);evidence[normal.key]['q']*=.4
  r=b.update(.20,2,evidence)
  self.assertEqual(b.selected.key,normal.key);self.assertEqual(r['pending_frames'],1);self.assertEqual(r['pending_span'],0)
if __name__=='__main__':unittest.main()
