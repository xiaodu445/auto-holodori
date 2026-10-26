"""Meaningful constraints and integration checks for the isolated v3 route."""
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from modular_agent.realtime.motion_states import LegalSignedTracker,BoundedSwingTracker,BoundedTrajectory
from modular_agent.realtime.jump_rope import load,phase_rope_components,run_jump_rope

ROOT=Path(__file__).resolve().parents[1]


class MotionConstraintTests(unittest.TestCase):
    def lock(self,tracker,direction=1):
        for i in range(20):
            result=tracker.update(i*.02,(.5+direction*i*.02)%1,.9)
            tracker.feedback(True,i*.02)
        return result

    def test_rotation_does_not_freeze_when_correction_opposes_travel(self):
        tracker=LegalSignedTracker(1);old=self.lock(tracker,-1)
        before=tracker.phase
        result=tracker.update(.4,(tracker.phase+.025)%1,.6)
        self.assertLess(result['phase_unwrapped'],before)
        self.assertTrue(result['blocked_correction'])

    def test_unsupported_curve_does_not_keep_narrow_high_confidence(self):
        tracker=LegalSignedTracker(1);self.lock(tracker)
        for i in range(20,40):
            tracker.update(i*.02,(.5+i*.02)%1,.8);tracker.feedback(False,i*.02)
        self.assertTrue(tracker.search_wide)
        self.assertGreaterEqual(tracker.uncertainty,.15)
        self.assertLess(tracker.confidence,.2)

    def test_long_zero_rate_in_rotation_becomes_uncertain_moving_prior(self):
        tracker=LegalSignedTracker(1);tracker.locked=True;tracker.time=0;tracker.rate=0
        states=[tracker.update(i*.02,None,0) for i in range(1,38)]
        self.assertTrue(any(s['search_wide'] for s in states))
        self.assertGreater(abs(states[-1]['rate']),.1)
        self.assertFalse(states[-1]['observed'])

    def test_single_outlier_cannot_reverse_rotation(self):
        tracker=LegalSignedTracker(1);self.lock(tracker)
        tracker.update(.4,.79,.6)
        for i in range(21,60):tracker.update(i*.02,(.5+i*.02)%1,.9)
        self.assertEqual(tracker.direction,1)
        self.assertEqual(tracker.reversals,0)

    def test_swing_remains_bounded_and_turns_during_occlusion(self):
        tracker=BoundedSwingTracker(2.394);tracker.phase=.98;tracker.time=0;tracker.locked=True
        states=[tracker.update(i*.02,None,0) for i in range(1,160)]
        self.assertTrue(all(0<=s['phase']<=1 for s in states))
        self.assertTrue(any(s['rate']<-.1 for s in states))
        self.assertTrue(any(s['rate']>.1 for s in states))
        self.assertTrue(all(not s['observed'] for s in states))
        self.assertGreater(states[-1]['predicted_turns'],0)

    def test_stationary_middle_is_not_a_permanent_swing_turn(self):
        tracker=BoundedSwingTracker(2.394);tracker.phase=.5;tracker.time=0;tracker.locked=True;tracker.rate=0
        tracker.zero_since=0
        result=tracker.update(.15,.5,.9)
        self.assertFalse(result['observed'])
        self.assertGreater(abs(result['phase']-.5),.01)

    def test_finite_clock_and_invalid_swing_coordinates_rejected(self):
        tracker=BoundedSwingTracker(2.394);tracker.update(0)
        for now,position in ((0,.5),(1,float('nan')),(1,1.1),(float('nan'),.5)):
            with self.assertRaises(ValueError):tracker.update(now,position,.9)

    def test_zero_timeout_configuration_checked(self):
        for value in (0,10,float('nan')):
            with self.assertRaises(ValueError):LegalSignedTracker(1,zero_timeout=value)
            with self.assertRaises(ValueError):BoundedSwingTracker(2.394,zero_timeout=value)


class SwingAssetTests(unittest.TestCase):
    def data(self):return json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/swing_v1.json').read_text(encoding='utf-8'))

    def test_bounded_path_is_not_cyclic_and_stays_smooth(self):
        atlas=BoundedTrajectory(self.data())
        self.assertTrue(np.allclose(atlas.curves(-1),atlas.curves(0)))
        self.assertTrue(np.allclose(atlas.curves(2),atlas.curves(1)))
        self.assertFalse(np.allclose(atlas.curves(0),atlas.curves(1)))
        curves=atlas.curves(np.linspace(0,1,101))
        self.assertLess(float(np.max(np.linalg.norm(np.diff(curves,axis=0),axis=2))),.03)
        self.assertLess(float(np.max(abs(np.diff(curves[:,:,1],n=3,axis=1)))),1e-7)

    def test_bad_asset_rejected(self):
        data=self.data();data['samples'][1]['coordinate']=0
        with self.assertRaises(ValueError):BoundedTrajectory(data)
        data=self.data();data['samples'][0]['curve'][0][1]=float('nan')
        with self.assertRaises(ValueError):BoundedTrajectory(data)

    def test_offline_robust_fit_recovers_smooth_rope(self):
        from modular_agent.realtime.build_jump_rope_swing import fit_quadratic
        rng=np.random.default_rng(7);x=np.linspace(.23,.79,700);u=(x-.225)/.594;y=.60-.20*u+.12*4*u*(1-u)
        x=np.r_[x,rng.uniform(.23,.79,100)];y=np.r_[y,rng.uniform(.36,.69,100)]
        curve,support=fit_quadratic(x,y,rng);u=(curve[:,0]-.225)/.594
        self.assertGreater(support,.7)
        self.assertLess(float(np.max(abs(curve[:,1]-(.60-.20*u+.12*4*u*(1-u))))),.004)


class StateRouteTests(unittest.TestCase):
    def vision(self):
        c,m,_=load(ROOT);v,controller=phase_rope_components(ROOT,c,m,state=True)
        return c,v,controller

    def test_blank_scene_keeps_legal_hypothesis_but_no_observation_or_input(self):
        c,v,controller=self.vision();image=np.zeros((180,320,3),np.uint8)
        for i in range(8):o=v.detect(image,i*.02)
        self.assertEqual(o['motion_state'],'rotation_forward')
        self.assertTrue(o['model_exists']);self.assertFalse(o['rope_valid'])
        d=controller(c).step(o,.2,True)
        self.assertFalse(d['down']);self.assertNotIn('stop',d)

    def test_shared_features_exactly_match_baseline_evidence(self):
        c,v,_=self.vision();gray=np.random.default_rng(3).integers(0,255,(180,320),dtype=np.uint8)
        delta=np.full_like(gray,40);variation=np.full_like(gray,80);v.rotation.prepare(gray)
        edges=cv2.Canny(gray,25,70);v.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        moving=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8))
        v.motion_distance=cv2.distanceTransform(255-moving,cv2.DIST_L2,3);v.variation=variation
        indices=np.array([0,5,30,70,95]);old=v.rotation.evidence(gray,delta,variation,indices);new=v._evidence(v.rotation,gray,indices)
        for a,b in zip(old,new):self.assertTrue(np.allclose(a,b))

    def test_state_cli_cannot_send_input(self):
        from modular_agent.realtime import jump_rope
        for flag in ('--live','--experimental-live','--test-space'):
            with patch('sys.argv',['jump_rope','--phase-rope','--phase-state',flag]),patch.object(jump_rope,'ActionComputer') as computer:
                with self.assertRaises(SystemExit):jump_rope.main()
                computer.assert_not_called()

    def test_profiles_not_silently_combined(self):
        with self.assertRaisesRegex(ValueError,'requires phase-rope'):run_jump_rope(ROOT,None,0,phase_state=True)
        with self.assertRaisesRegex(ValueError,'choose v2'):run_jump_rope(ROOT,None,0,phase_rope=True,phase_reverse=True,phase_state=True)
        with self.assertRaisesRegex(ValueError,'judgment-only'):run_jump_rope(ROOT,None,0,phase_rope=True,phase_state=True,live=True)

class StateTransitionConstraintTests(unittest.TestCase):
    def test_candidate_chain_needs_continuity_before_reassociation(self):
        _,module,_=load(ROOT)
        # The domain loader keeps this route independent of the older visual modules.
        chain=module._state.CandidateChain(True)
        self.assertFalse(chain.update(.98,.9,0))
        self.assertFalse(chain.update(.01,.9,.03))
        self.assertTrue(chain.update(.04,.9,.06))
        self.assertFalse(chain.update(.5,.9,.08))
        self.assertEqual(len(chain.records),1)

    def test_swing_exit_search_cannot_select_lower_rotation_arc(self):
        c,module,_=load(ROOT);v,_=phase_rope_components(ROOT,c,module,state=True)
        gray=np.zeros((180,320),np.uint8)
        def evidence(vision,gray,indices):
            count=len(indices)
            return np.linspace(.4,.9,count),np.zeros((count,41,2)),np.ones((count,41),dtype=bool),np.ones(count),np.ones(count)
        with patch.object(v,'_evidence',side_effect=evidence):
            chosen=v._select(v.rotation,gray,gray,gray,0,global_search=True,upper_only=True)
        self.assertLess(v.rotation.atlas.curves(chosen['phase'])[20,1],.33)
        self.assertLess(chosen['evaluated'],96)


class ImmediateCoastingTests(unittest.TestCase):
    def vision(self):
        c,module,_=load(ROOT)
        return phase_rope_components(ROOT,c,module,state=True)[0]

    def candidate(self,vision,atlas,phase,seen=True):
        l,t,_,_=vision.c['roi']
        return dict(phase=phase%1,raw=(atlas.curves(phase)-[l,t])*vision.units,
            seen=np.full(41,seen,dtype=bool),moving=.2)

    def test_first_lost_frame_advances_exact_prior_in_both_directions(self):
        for direction in (-1,1):
            v=self.vision();vision=v.rotation;vision.prepare(np.zeros((180,320),np.uint8))
            tracker=vision.tracker;tracker.locked=True;tracker.time=1.;tracker.phase=.4
            tracker.direction=direction;tracker.rate=direction*.8;tracker.confidence=.8
            tracker.history=[(.96,.37,.9),(1.,.4,.9)]
            old=list(tracker.history)
            candidate=self.candidate(vision,vision.atlas,.4,seen=False)
            result,curve,support,valid=v._advance(vision,vision.atlas,candidate,.9,1.02,rotation=True)
            self.assertAlmostEqual(result['phase_unwrapped'],.4+direction*.8*.02)
            self.assertAlmostEqual(result['rate'],direction*.8)
            self.assertEqual(tracker.history,old)
            self.assertFalse(result['observed']);self.assertFalse(valid)
            self.assertTrue(tracker.search_wide)
            self.assertEqual(result['continuation'],'prior_prediction')
            json.dumps(result)

    def test_wrong_visible_curve_cannot_modify_rate_or_history(self):
        v=self.vision();vision=v.rotation;vision.prepare(np.zeros((180,320),np.uint8))
        tracker=vision.tracker;tracker.locked=True;tracker.time=1.;tracker.phase=.4;tracker.rate=.8
        for i in range(1,10):
            candidate=self.candidate(vision,vision.atlas,.1)
            result,_,_,_=v._advance(vision,vision.atlas,candidate,.9,1+i*.02,rotation=True)
            self.assertAlmostEqual(tracker.phase,.4+.8*i*.02)
            self.assertAlmostEqual(tracker.rate,.8)
            self.assertFalse(result['observed'])
        self.assertEqual(tracker.history,[])

    def test_supported_zero_rate_during_descent_is_rejected_immediately(self):
        v=self.vision();vision=v.rotation;vision.prepare(np.zeros((180,320),np.uint8))
        tracker=vision.tracker;tracker.locked=True;tracker.time=1.;tracker.rate=.8;tracker.confidence=.8
        # Find a descending portion of the actual atlas, rather than assuming phase meaning.
        phase=next(p for p in np.linspace(0,1,96,endpoint=False)
            if vision.atlas.curves(p+.016)[20,1]>vision.atlas.curves(p)[20,1]+.001)
        tracker.phase=phase;tracker.good_rate=.8
        candidate=self.candidate(vision,vision.atlas,phase+.016)
        original=tracker.update
        def contaminated(now,visual_phase=None,quality=0.):
            result=original(now,visual_phase,quality)
            if visual_phase is not None:
                tracker.rate=0.;result.update(rate=0.,observed=True)
                tracker.history.append((now,99.,1.))
            return result
        with patch.object(tracker,'update',side_effect=contaminated):
            result,_,_,_=v._advance(vision,vision.atlas,candidate,.9,1.02,rotation=True)
        self.assertEqual(result['association_rejection'],'descending_zero_rate')
        self.assertAlmostEqual(result['phase_unwrapped'],phase+.016)
        self.assertAlmostEqual(result['rate'],.8)
        self.assertEqual(tracker.history,[])

    def test_first_occluded_swing_frame_follows_bounded_prediction(self):
        v=self.vision();vision=v.swing;vision.prepare(np.zeros((180,320),np.uint8))
        tracker=vision.tracker;tracker.locked=True;tracker.time=1.;tracker.phase=.98;tracker.rate=.2
        predicted=tracker.predict(1.02)
        candidate=self.candidate(vision,v.swing_atlas,.98,seen=False)
        result,_,_,_=v._advance(vision,v.swing_atlas,candidate,.9,1.02)
        self.assertAlmostEqual(result['phase'],predicted)
        self.assertTrue(tracker.search_wide)
        self.assertFalse(result['observed'])


    def test_swing_position_correction_cannot_cancel_predicted_motion(self):
        v=self.vision();vision=v.swing;vision.prepare(np.zeros((180,320),np.uint8))
        tracker=vision.tracker;tracker.locked=True;tracker.time=1.;tracker.phase=.98
        tracker.rate=.2;tracker.confidence=.8
        expected=tracker.predict(1.02);original=tracker.update
        candidate=self.candidate(vision,v.swing_atlas,.98)
        def stalled(now,visual_phase=None,quality=0.):
            result=original(now,visual_phase,quality)
            if visual_phase is not None:
                tracker.phase=.98;result.update(phase=.98,phase_unwrapped=.98,observed=True)
            return result
        with patch.object(tracker,'update',side_effect=stalled):
            result,_,_,_=v._advance(vision,v.swing_atlas,candidate,.9,1.02)
        self.assertEqual(result['association_rejection'],'correction_cancelled_prediction')
        self.assertAlmostEqual(result['phase'],expected)
        self.assertFalse(result['observed'])
