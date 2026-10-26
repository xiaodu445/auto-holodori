import json
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from modular_agent.realtime.phase_tracking import CyclicTrajectory,PhaseTracker
from modular_agent.realtime.jump_rope import load,phase_rope_components,run_jump_rope

ROOT=Path(__file__).resolve().parents[1]

class PhaseTests(unittest.TestCase):
 def setUp(self):
  self.data=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/rotation_v1.json').read_text(encoding='utf-8'))
  self.atlas=CyclicTrajectory(self.data)
 def test_cyclic_wrap_and_shapes(self):
  self.assertTrue(np.allclose(self.atlas.curves(.99),self.atlas.curves(-.01)))
  self.assertEqual(self.atlas.curves([.1,.2]).shape,(2,41,2))
  self.assertLess(float(np.max(abs(self.atlas.curves(.99999)-self.atlas.curves(.00001)))),.001)
 def test_atlas_rejects_unknown_mode_and_nonfinite_points(self):
  for bad in (dict(self.data,mode='swing'),dict(self.data,reference_period=float('nan'))):
   with self.assertRaises(ValueError):CyclicTrajectory(bad)
 def lock(self,tracker):
  for i in range(8):result=tracker.update(i*.02,(.3+i*.02)%1,.8)
  self.assertTrue(result['locked']);return result
 def test_no_image_retains_progress_and_decays_confidence(self):
  tracker=PhaseTracker(1);previous=self.lock(tracker)
  result=tracker.update(1.14,None,0)
  self.assertTrue(result['locked']);self.assertGreater(result['phase_unwrapped'],previous['phase_unwrapped'])
  self.assertLess(result['confidence'],previous['confidence']);self.assertGreater(result['uncertainty'],previous['uncertainty'])
  self.assertFalse(result['observed']);self.assertEqual(result['status'],'searching_with_prediction')
 def test_phase_wrap_does_not_reverse_progress(self):
  tracker=PhaseTracker(1)
  states=[tracker.update(i*.02,(.9+i*.02)%1,.8) for i in range(20)]
  self.assertTrue(states[-1]['locked'])
  self.assertTrue(all(b['phase_unwrapped']>=a['phase_unwrapped'] for a,b in zip(states[3:],states[4:])))
 def test_speed_changes_update_rate_not_fixed_interval(self):
  tracker=PhaseTracker(1);self.lock(tracker)
  for i in range(8,35):result=tracker.update(i*.02,(.44+(i-7)*.02*1.8)%1,.8)
  self.assertGreater(result['rate'],1.3)
 def test_distant_candidate_cannot_instantly_replace_locked_phase(self):
  tracker=PhaseTracker(1);old=self.lock(tracker)
  result=tracker.update(.16,(old['phase']+.4)%1,.9)
  self.assertLess(result['phase_unwrapped']-old['phase_unwrapped'],.05)
  self.assertFalse(result['observed'])
 def test_nonmonotonic_clock_rejected(self):
  tracker=PhaseTracker(1);tracker.update(1)
  with self.assertRaises(ValueError):tracker.update(1)
 def test_blank_image_has_model_but_no_detection(self):
  c,m,_=load(ROOT);v,controller=phase_rope_components(ROOT,c,m)
  for i in range(6):o=v.detect(np.zeros((300,600,3),np.uint8),i*.02)
  self.assertTrue(o['model_exists']);self.assertEqual(len(o['whole_curve']),41)
  self.assertFalse(o['rope_valid']);self.assertEqual(o['phase_estimate']['confidence'],0)
  d=controller(c).step(o,.1,True)
  self.assertFalse(d['down']);self.assertNotIn('stop',d)
 def test_live_api_rejected_before_any_window_or_input(self):
  with self.assertRaisesRegex(ValueError,'judgment-only'):run_jump_rope(ROOT,None,0,phase_rope=True,live=True)
  with self.assertRaisesRegex(ValueError,'choose one'):run_jump_rope(ROOT,None,0,phase_rope=True,local_motion=True)
 def test_cli_rejects_all_input_flags_before_computer(self):
  from modular_agent.realtime import jump_rope
  for flag in ('--live','--experimental-live','--test-space'):
   with patch('sys.argv',['jump_rope','--phase-rope',flag]),patch.object(jump_rope,'ActionComputer') as computer:
    with self.assertRaises(SystemExit):jump_rope.main()
    computer.assert_not_called()

class AtlasFitTests(unittest.TestCase):
 def test_training_fit_recovers_curve_with_outliers(self):
  from modular_agent.realtime.build_jump_rope_atlas import fit_curve
  rng=np.random.default_rng(7);x=np.linspace(.22,.82,700);y=.2+2*(x-.52)**2
  x=np.r_[x,rng.uniform(.22,.82,100)];y=np.r_[y,rng.uniform(.1,.7,100)]
  curve,support=fit_curve(x,y,rng)
  self.assertGreater(support,.7)
  self.assertLess(float(np.max(abs(curve[:,1]-(.2+2*(curve[:,0]-.52)**2)))),.003)

class PhaseIntegrationTests(unittest.TestCase):
 def test_restricted_phase_evidence_matches_full_search(self):
  c,m,_=load(ROOT);v,_=phase_rope_components(ROOT,c,m)
  gray=np.random.default_rng(3).integers(0,255,(180,320),dtype=np.uint8)
  v.prepare(gray);delta=np.full_like(gray,40);variation=np.full_like(gray,80)
  full=v.evidence(gray,delta,variation);indices=np.array([0,7,30,70,95])
  small=v.evidence(gray,delta,variation,indices)
  for a,b in zip(small,full):self.assertTrue(np.allclose(a,b[indices]))
 def test_route_catalog_links_and_legacy_launchers_exist(self):
  catalog=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_routes.json').read_text(encoding='utf-8'))
  self.assertEqual(catalog['current_auto'],'local_motion_v6')
  for route in catalog['routes']:
   self.assertTrue((ROOT/route['documentation']).is_file(),route)
   self.assertTrue((ROOT/route['judgment_launcher']).is_file(),route)
   for file in route['files']:self.assertTrue((ROOT/'domains/hololive_dreams/models/jump_rope'/file).is_file(),route)
 def test_preview_distinguishes_uncertain_persistent_curve(self):
  from modular_agent.realtime.jump_rope_preview import render_frame
  c,m,_=load(ROOT);v,_=phase_rope_components(ROOT,c,m)
  image=np.zeros((180,320,3),np.uint8);o=v.detect(image,0)
  displayed=render_frame(image,o,{},c,0)
  self.assertEqual(displayed.shape,(397,320,3))
  self.assertTrue(o['model_exists']);self.assertFalse(o['rope_valid'])
 def test_sample_point_metric_uses_pixel_aspect_ratio(self):
  from modular_agent.realtime.validate_jump_rope_phase import point_errors
  error=point_errors([[0,0],[1,0]],[[50,10]],[100,50])
  self.assertAlmostEqual(float(error[0]),10)

class SignedPhaseTests(unittest.TestCase):
 def tracker(self):
  from modular_agent.realtime.phase_tracking import SignedPhaseTracker
  return SignedPhaseTracker(1)
 def feed(self,tracker,start,phases):
  return [tracker.update((start+i)*.02,p%1,.9) for i,p in enumerate(phases)]
 def test_forward_rotation_stays_forward_through_wrap(self):
  tracker=self.tracker();states=self.feed(tracker,0,[.8+i*.02 for i in range(100)])
  self.assertEqual(states[-1]['reversals'],0);self.assertGreater(states[-1]['rate'],.9)
  self.assertTrue(all(b['phase_unwrapped']>=a['phase_unwrapped'] for a,b in zip(states[3:],states[4:])))
 def test_continuous_turn_reverses_and_returns_forward(self):
  tracker=self.tracker();phase=.8;states=[]
  for i in range(90):
   if i:phase+=(1 if i<30 or i>=60 else -1)*.02
   states.append(tracker.update(i*.02,phase%1,.9))
  self.assertEqual(states[50]['direction'],-1);self.assertLess(states[50]['rate'],-.8)
  self.assertEqual(states[-1]['direction'],1);self.assertEqual(states[-1]['reversals'],2)
  self.assertTrue(all(abs(b['phase_unwrapped']-a['phase_unwrapped'])<.06 for a,b in zip(states[3:],states[4:])))
 def test_backward_acquisition_crosses_zero(self):
  tracker=self.tracker();states=self.feed(tracker,0,[.08-i*.012 for i in range(60)])
  self.assertTrue(states[-1]['locked']);self.assertEqual(states[-1]['direction'],-1)
  self.assertLess(states[-1]['rate'],-.5)
  self.assertLess(abs((states[-1]['phase']-(.08-59*.012)+.5)%1-.5),.03)
 def test_one_backward_outlier_does_not_reverse(self):
  tracker=self.tracker();self.feed(tracker,0,[.3+i*.02 for i in range(20)])
  tracker.update(.40,.60,.9)
  states=self.feed(tracker,21,[.3+i*.02 for i in range(21,60)])
  self.assertEqual(states[-1]['reversals'],0);self.assertGreater(states[-1]['rate'],.8)
 def test_rejected_candidate_does_not_change_rate_or_history(self):
  tracker=self.tracker();old=self.feed(tracker,0,[.3+i*.02 for i in range(20)])[-1]
  before=tracker.rate;history=list(tracker.history)
  state=tracker.update(.4,(old['phase']+.4)%1,.9)
  self.assertFalse(state['observed']);self.assertEqual(tracker.rate,before);self.assertEqual(tracker.history,history)
 def test_occlusion_preserves_signed_direction_and_rate(self):
  tracker=self.tracker();old=self.feed(tracker,0,[.5-i*.02 for i in range(30)])[-1]
  new=tracker.update(.68,None,0)
  self.assertEqual(new['direction'],-1);self.assertLess(new['phase_unwrapped'],old['phase_unwrapped'])
  self.assertEqual(new['rate'],old['rate']);self.assertFalse(new['observed'])
 def test_direction_does_not_switch_on_stationary_jitter(self):
  tracker=self.tracker();self.feed(tracker,0,[.3+i*.02 for i in range(20)])
  states=self.feed(tracker,20,[.68+(.002 if i%2 else -.002) for i in range(60)])
  self.assertEqual(states[-1]['reversals'],0)
 def test_signed_route_is_separate_and_rejects_input(self):
  c,m,_=load(ROOT);v,_=phase_rope_components(ROOT,c,m,reverse=True)
  self.assertTrue(v.settings['allow_reverse']);self.assertTrue(c['phase_reverse'])
  with self.assertRaisesRegex(ValueError,'judgment-only'):run_jump_rope(ROOT,None,0,phase_rope=True,phase_reverse=True,live=True)
  with self.assertRaisesRegex(ValueError,'requires phase-rope'):run_jump_rope(ROOT,None,0,phase_reverse=True)
 def test_clock_and_quality_still_validated(self):
  tracker=self.tracker();tracker.update(1)
  for now,phase,q in ((1,None,0),(2,float('nan'),.9),(2,.2,float('nan'))):
   with self.assertRaises(ValueError):tracker.update(now,phase,q)

class SignedRouteIntegrationTests(unittest.TestCase):
 def test_cli_reverse_rejects_all_input_before_computer(self):
  from modular_agent.realtime import jump_rope
  for flag in ('--live','--experimental-live','--test-space'):
   with patch('sys.argv',['jump_rope','--phase-rope','--phase-reverse',flag]),patch.object(jump_rope,'ActionComputer') as computer:
    with self.assertRaises(SystemExit):jump_rope.main()
    computer.assert_not_called()
 def test_reverse_replay_keeps_forward_artifact_and_has_no_input(self):
  import tempfile
  from modular_agent.realtime import jump_rope
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);old=root/'runtime/jump-rope/phase/replay.json';old.parent.mkdir(parents=True);old.write_text('forward-result',encoding='utf-8')
   video=root/'source.avi';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),50,(320,180))
   self.assertTrue(writer.isOpened())
   for _ in range(6):writer.write(np.zeros((180,320,3),np.uint8))
   writer.release()
   with patch.object(jump_rope,'load',side_effect=lambda *args,**kw:load(ROOT)),patch.object(jump_rope,'phase_rope_components',side_effect=lambda _,c,m,reverse=False:phase_rope_components(ROOT,c,m,reverse=reverse)):
    result=jump_rope.replay(root,video,phase_rope=True,phase_reverse=True)
   self.assertEqual(old.read_text(encoding='utf-8'),'forward-result')
   self.assertEqual(Path(result['output']).parent.name,'phase-reverse')
   self.assertEqual(result['simulated_jumps'],0)
   rows=json.loads(Path(result['output']).read_text(encoding='utf-8'))
   self.assertTrue(all(not r['decision']['down'] for r in rows))
