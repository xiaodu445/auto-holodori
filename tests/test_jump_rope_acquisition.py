import unittest
from pathlib import Path
import numpy as np
import cv2
from modular_agent.realtime.jump_rope import load
ROOT=Path(__file__).resolve().parents[1]

class JumpRopeAcquisitionTests(unittest.TestCase):
    def setUp(self):self.c,self.m,self.v=load(ROOT)
    def obs(self, valid=True):
        return dict(valid=valid,avatar_valid=True,avatar_y=self.c['avatar_template'][1],rope_valid=valid,rope_y=.4 if valid else None,hue=100 if valid else None,hearts=3)

    def test_initial_missing_rope_waits_without_input(self):
        p=self.m.JumpRopeController(self.c)
        for t in (0,.1,.2,.3,.4,.5,.6,1):
            # Real cadence must be below max_observation_gap.
            p.last_time=t-.02
            d=p.step(self.obs(False),t,True)
            self.assertFalse(d['down']);self.assertNotIn('stop',d)
        self.assertFalse(p.tracking_established)

    def test_initial_missing_continues_searching_after_twenty_seconds(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(1002):
            d=p.step(self.obs(False),i*.02)
            if d.get('stop'):break
        self.assertNotIn('stop',d)
        self.assertEqual(d['input_inhibited'],'searching_for_track')
        self.assertFalse(d['down'])

    def test_long_loss_reacquires_without_stale_predictions_or_inputs(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(4):p.step(self.obs(),i*.02)
        self.assertTrue(p.tracking_established)
        d=p.step(self.obs(False),.08,True)
        self.assertFalse(d['down']);self.assertNotIn('stop',d)
        for i in range(5,35):
            d=p.step(self.obs(False),i*.02,True)
            if d.get('stop'):break
        self.assertNotIn('stop',d)
        self.assertFalse(p.tracking_established)
        self.assertFalse(d['down'])
        self.assertIsNone(p.pending)
        self.assertEqual(len(p.samples),0)
        for i in range(35,38):
            d=p.step(self.obs(),i*.02)
            self.assertFalse(d['down'])
        self.assertTrue(p.tracking_established)
        self.assertEqual(len(p.samples),1)
        self.assertEqual(d['input_inhibited'],'acquiring_motion')

    def test_avatar_alone_does_not_erase_recovery_state(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(4):p.step(self.obs(),i*.02)
        for i in range(4,50):
            d=p.step(self.obs(False),i*.02)
        self.assertEqual(p.state,'recovering')
        self.assertEqual(d['input_inhibited'],'reacquiring_track')
        self.assertFalse(d['down'])
        self.assertFalse(p.tracking_established)

    def test_unstable_rope_does_not_arm_controller(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(20):p.step(self.obs(i%2==0),i*.02)
        self.assertFalse(p.tracking_established)
        self.assertEqual(p.jumps,0)

    def test_reset_requires_reacquisition(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(4):p.step(self.obs(),i*.02)
        p.reset_motion()
        self.assertFalse(p.tracking_established)
        self.assertFalse(p.step(self.obs(),1)['down'])

    def synthetic(self,two=False,patch=False):
        image=np.zeros((400,960,3),np.uint8)
        l,t,r,b=self.c['roi']
        color=tuple(int(x) for x in cv2.cvtColor(np.uint8([[[100,120,210]]]),cv2.COLOR_HSV2BGR)[0,0])
        for x1,x2 in self.c['rope_probes']:
            left=round((x1-l)/(r-l)*960);right=round((x2-l)/(r-l)*960)
            y=round((.4-t)/(b-t)*400)
            if patch:cv2.rectangle(image,(left,y-15),(right,y+15),color,-1)
            else:cv2.line(image,(left-2,y-4),(right+2,y+4),color,2)
            if two:cv2.line(image,(left-2,y+26),(right+2,y+34),color,2)
        return image

    def test_slanted_thin_rope_supported(self):
        o=self.v.detect(self.synthetic())
        self.assertTrue(o['rope_valid']);self.assertEqual(o['probe_candidates'],[1,1])
        self.assertAlmostEqual(o['rope_y'],.4,delta=.005)

    def test_yellow_rope_acquires_without_blue_history(self):
        self.c['joint_shape_motion']=True
        im=self.synthetic()
        yellow=tuple(int(x) for x in cv2.cvtColor(np.uint8([[[27,210,220]]]),cv2.COLOR_HSV2BGR)[0,0])
        im[np.any(im!=0,axis=2)]=yellow
        o=self.v.detect(im,timestamp=0)
        self.assertTrue(o['rope_valid'],o)
        self.assertAlmostEqual(o['rope_y'],.4,delta=.006)
        self.assertFalse(o['color_changed'])

    def test_yellow_rope_does_not_merge_with_green_scenery(self):
        im=self.synthetic()
        yellow=tuple(int(x) for x in cv2.cvtColor(np.uint8([[[27,210,220]]]),cv2.COLOR_HSV2BGR)[0,0])
        green=tuple(int(x) for x in cv2.cvtColor(np.uint8([[[65,210,220]]]),cv2.COLOR_HSV2BGR)[0,0])
        im[np.any(im!=0,axis=2)]=yellow
        l,t,r,b=self.c['roi'];y=round((.4-t)/(b-t)*im.shape[0])
        for x1,x2 in self.c['rope_probes']:
            x=round((x2-l)/(r-l)*im.shape[1])
            cv2.rectangle(im,(x-3,y+6),(x+8,y+35),green,-1)
        self.assertTrue(self.v.detect(im,timestamp=0)['rope_valid'])

    def test_small_rope_gap_preserves_geometry(self):
        im=self.synthetic();l,t,r,b=self.c['roi']
        for x1,x2 in self.c['rope_probes']:
            mid=round(((x1+x2)/2-l)/(r-l)*im.shape[1])
            im[:,mid-3:mid+3]=0
        o=self.v.detect(im,timestamp=0)
        self.assertTrue(o['rope_valid'],o)

    def test_multiple_lines_and_broad_background_rejected(self):
        self.assertFalse(self.v.detect(self.synthetic(two=True))['rope_valid'])
        self.assertFalse(self.v.detect(self.synthetic(patch=True))['rope_valid'])
        self.assertFalse(self.v.detect(np.zeros((400,960,3),np.uint8))['rope_valid'])

class JumpRopeTemporalTests(unittest.TestCase):
    setUp=JumpRopeAcquisitionTests.setUp
    obs=JumpRopeAcquisitionTests.obs
    synthetic=JumpRopeAcquisitionTests.synthetic
    def test_history_selects_moving_rope_among_distractors(self):
        first=self.v.detect(self.synthetic(),timestamp=0)
        self.assertTrue(first['rope_valid'])
        second=self.v.detect(self.synthetic(two=True),timestamp=.02)
        self.assertTrue(second['rope_valid'],second)
        self.assertAlmostEqual(second['rope_y'],first['rope_y'],delta=.006)
        self.assertTrue(all(p is not None for p in second['probe_prediction']))
        self.v.reset()
        self.assertFalse(self.v.detect(self.synthetic(two=True),timestamp=.04)['rope_valid'])

    def test_visible_side_keeps_history_while_partner_is_occluded(self):
        im=self.synthetic();self.v.detect(im,timestamp=0)
        l,t,r,b=self.c['roi'];x1,x2=self.c['rope_probes'][1]
        left=round((x1-l)/(r-l)*im.shape[1]);right=round((x2-l)/(r-l)*im.shape[1])
        im[:,left-3:right+4]=0
        for i in range(1,10):
            o=self.v.detect(im,timestamp=i*.02)
            self.assertFalse(o['rope_valid'])
            self.assertIsNone(o['rope_y'])
        self.assertAlmostEqual(self.v.previous[0]['time'],.18)
        self.assertIsNone(self.v.previous[1])

    def curve_candidate(self,xs,center=.4,slope=.2,curvature=2,motion=1):
        points=[[x,center+slope*(x-.565)+curvature*(x-.565)**2] for x in xs]
        return dict(y=float(np.mean([p[1] for p in points])),points=points,hue=100,saturation=120,family='configured',motion=motion)

    def test_joint_shape_chooses_coherent_pair_over_pulled_endpoint(self):
        left=self.curve_candidate([.50,.512,.525])
        right=self.curve_candidate([.605,.617,.63])
        pulled=self.curve_candidate([.605,.617,.63],center=.46,slope=-.8)
        pair=self.v._joint([left],[pulled,right],0)
        self.assertIsNotNone(pair)
        self.assertIs(pair[2],right)
        self.assertAlmostEqual(pair[3][2],.4)

    def test_joint_rejects_impossible_tilt_and_prefers_moving_pair(self):
        left=self.curve_candidate([.50,.512,.525],slope=.9,curvature=0)
        right=self.curve_candidate([.605,.617,.63],slope=.9,curvature=0)
        self.assertIsNone(self.v._joint([left],[right],0))
        self.v.motion_mask=np.ones((400,960),dtype=np.uint8)
        left=self.curve_candidate([.50,.512,.525],motion=0)
        right=self.curve_candidate([.605,.617,.63],motion=0)
        moving_left=self.curve_candidate([.50,.512,.525],center=.48,motion=1)
        moving_right=self.curve_candidate([.605,.617,.63],center=.48,motion=1)
        pair=self.v._joint([left,moving_left],[right,moving_right],0)
        self.assertIsNotNone(pair)
        self.assertIs(pair[1],moving_left)

    def test_persistent_static_pair_unlocks_and_moving_pair_reacquires(self):
        self.v.motion_mask=np.ones((400,960),dtype=np.uint8)
        left=self.curve_candidate([.50,.512,.525],motion=0)
        right=self.curve_candidate([.605,.617,.63],motion=0)
        pair=self.v._joint([left],[right],0)
        self.assertIsNotNone(self.v._check_pair_motion(pair,0))
        self.assertIsNone(self.v._check_pair_motion(pair,.26))
        self.assertTrue(self.v.reject_static)
        self.assertEqual(self.v.previous,[None,None])
        self.assertIsNone(self.v._joint([left],[right],.28))
        left['motion']=right['motion']=1
        recovered=self.v._check_pair_motion(self.v._joint([left],[right],.30),.30)
        self.assertIsNotNone(recovered)
        self.assertFalse(self.v.reject_static)

    def test_history_expires_and_blank_is_not_predicted_measurement(self):
        self.v.detect(self.synthetic(),timestamp=0)
        lost=self.v.detect(np.zeros((400,960,3),np.uint8),timestamp=.02)
        self.assertFalse(lost['rope_valid'])
        self.assertIsNone(lost['rope_y'])
        expired=self.v.detect(self.synthetic(two=True),timestamp=.5)
        self.assertFalse(expired['rope_valid'])
        self.assertEqual(expired['probe_prediction'],[None,None])

    def test_color_change_keeps_tracking_without_changing_control_mode(self):
        white=self.synthetic();white[np.any(white!=0,axis=2)]=[225,225,225]
        self.assertTrue(self.v.detect(white,timestamp=0)['rope_valid'])
        self.v.reset();self.v.detect(self.synthetic(),timestamp=0)
        changed=self.v.detect(white,timestamp=.02)
        self.assertTrue(changed['rope_valid'],changed)
        self.assertFalse(changed['color_changed'])
        self.assertFalse(changed['color_uncertain'])
        changed=self.v.detect(white,timestamp=.04)
        self.assertFalse(changed['color_changed'])
        p=self.m.JumpRopeController(self.c)
        for i in range(3):p.step(self.obs(),i*.02)
        o=self.obs();o['color_changed']=True
        decision=p.step(o,.06)
        self.assertEqual(p.mode,'rotation')
        self.assertEqual(len(p.samples),2)
        self.assertFalse(decision['down'])

    def test_dim_blue_fallback_is_not_a_skill_change(self):
        initial=self.v.detect(self.synthetic(),timestamp=0)
        dim=self.synthetic()
        color=tuple(int(x) for x in cv2.cvtColor(np.uint8([[[100,120,145]]]),cv2.COLOR_HSV2BGR)[0,0])
        dim[np.any(dim!=0,axis=2)]=color
        for i in range(1,5):
            o=self.v.detect(dim,timestamp=i*.02)
            self.assertTrue(o['rope_valid'],o)
            self.assertFalse(o['color_changed'])
            self.assertFalse(o['color_uncertain'])

    def test_alternate_mask_same_blue_is_not_color_change(self):
        # Force the wide mask while preserving actual hue and saturation.
        self.v.detect(self.synthetic(),timestamp=0)
        self.c['rope_hsv_ranges']=[[[95,50,220],[115,200,255]]]
        for i in range(1,5):
            o=self.v.detect(self.synthetic(),timestamp=i*.02)
            self.assertTrue(o['rope_valid'],o)
            self.assertEqual(o['selection_method'],'fallback')
            self.assertFalse(o['color_changed'])
            self.assertFalse(o['color_uncertain'])

    def test_same_motion_different_colors_has_identical_control(self):
        a=self.m.JumpRopeController(self.c);b=self.m.JumpRopeController(self.c)
        for i in range(20):
            o=self.obs();o['rope_y']=.35+i*.02*.5
            altered={**o,'hue':(i*35)%180,'color_changed':True,'color_uncertain':True}
            x=a.step(o,i*.02);y=b.step(altered,i*.02)
            self.assertEqual(x,y)
            self.assertEqual(a.mode,b.mode)
            self.assertEqual(list(a.samples),list(b.samples))

    def test_speed_change_without_color_change_invalidates_pending(self):
        p=self.m.JumpRopeController(self.c)
        for i in range(12):
            o=self.obs();o['rope_y']=.35+i*.02*.4
            p.step(o,i*.02)
        p.pending=1.0
        # A new actual track accelerates/reverses without a hue change.
        for i in range(12,18):
            o=self.obs();o['rope_y']=.438+(i-11)*.02*1.5
            d=p.step(o,i*.02)
            if d.get('input_inhibited')=='speed_changed':break
        self.assertEqual(d['input_inhibited'],'speed_changed')
        self.assertEqual(len(p.samples),self.c['fit_samples'])
        self.assertIsNone(p.pending)
        self.assertEqual(p.mode,'rotation')

    def test_accelerating_motion_keeps_history_and_can_trigger_jump(self):
        self.c['calibration'].update(verified=True,input_latency_seconds=.035,safe_airborne_seconds=.20,danger_y=.50,rotation_direction=1,max_prediction_error=.012)
        self.c['speed_change_ratio']=.10
        p=self.m.JumpRopeController(self.c);down=False
        for i in range(25):
            t=i*.016
            o=self.obs();o['rope_y']=.30+.2*t+1.5*t*t
            d=p.step(o,t,down);down=d['down']
        self.assertGreater(p.jumps,0)
        self.assertEqual(len(p.samples),self.c['fit_samples'])

    def test_trial_visible_crossing_triggers_once_and_releases(self):
        self.c['experimental_input']=True;self.c['demonstration_crossing_trial']=True
        p=self.m.JumpRopeController(self.c);down=False;edges=[]
        for i,y in enumerate([.20,.23,.26,.28,.31,.32,.33,.34]):
            o=self.obs();o['rope_y']=y
            d=p.step(o,i*.02,down);down=d['down'];edges.append(down)
        self.assertEqual(p.jumps,1)
        self.assertTrue(any(edges))
        self.assertFalse(edges[-1])
    def test_unobserved_jump_continues_without_retrying_same_pass(self):
        self.c['experimental_input']=True;self.c['demonstration_crossing_trial']=True
        p=self.m.JumpRopeController(self.c)
        for i in range(5):p.step(self.obs(),i*.02)
        p.jump_sent_at=.08;p.demo_pass_consumed=True
        for i in range(5,25):
            d=p.step(self.obs(),i*.02)
            self.assertNotIn('stop',d)
            self.assertFalse(d['down'])
        self.assertIsNone(p.jump_sent_at)
        self.assertTrue(p.demo_pass_consumed)

    def test_short_rope_loss_can_predict_once_but_expired_or_avatar_loss_cannot(self):
        for loss_time,avatar,expected in [(.10,True,True),(.24,True,False),(.10,False,False)]:
            c=dict(self.c);c['experimental_input']=True;c['demonstration_crossing_trial']=True
            p=self.m.JumpRopeController(c)
            for i,y in enumerate([.20,.21,.22,.23,.24]):
                o=self.obs();o['rope_y']=y;p.step(o,i*.02)
            p.last_time=loss_time-.02
            o=self.obs(False);o['avatar_valid']=avatar
            d=p.step(o,loss_time)
            self.assertEqual(d['down'],expected)
            self.assertNotIn('stop',d)
            if expected:
                self.assertEqual(d['trigger'],'short_occlusion_prediction_trial')
                self.assertTrue(p.step(o,loss_time+.02,True)['down'])
                self.assertFalse(p.step(o,loss_time+.04,True)['down'])
                self.assertEqual(p.jumps,1)

    def test_new_rotation_rearms_when_overhead_height_was_hidden(self):
        self.c['experimental_input']=True;self.c['demonstration_crossing_trial']=True
        p=self.m.JumpRopeController(self.c)
        p.demo_pass_consumed=True
        for i,y in enumerate([.45,.43,.40,.37,.34,.31,.32,.34,.36]):
            o=self.obs();o['rope_y']=y
            d=p.step(o,i*.02)
        self.assertEqual(p.jumps,1)
        self.assertTrue(p.demo_pass_consumed)
        self.assertFalse(p.seen_returning)

    def test_trial_reacquires_inside_visible_band_without_exact_line_crossing(self):
        self.c['experimental_input']=True;self.c['demonstration_crossing_trial']=True
        p=self.m.JumpRopeController(self.c)
        for i,y in enumerate([.33,.36,.39,.41]):
            o=self.obs();o['rope_y']=y
            d=p.step(o,i*.02)
        self.assertTrue(d['down'])
        self.assertEqual(d['trigger'],'demonstration_crossing_trial')
        self.assertEqual(p.jumps,1)

    def test_trial_does_not_jump_on_missing_or_reverse_crossing(self):
        self.c['experimental_input']=True;self.c['demonstration_crossing_trial']=True
        for invalid in (False,True):
            p=self.m.JumpRopeController(self.c)
            for i,y in enumerate([.40,.38,.35,.32,.29]):
                o=self.obs(not invalid);o['rope_y']=y
                d=p.step(o,i*.02)
                self.assertFalse(d['down'])
            self.assertEqual(p.jumps,0)

    def test_no_ui_required_for_acquisition_or_calibrated_jump(self):
        self.c['calibration'].update(verified=True,input_latency_seconds=.035,safe_airborne_seconds=.20,danger_y=.50,rotation_direction=1,max_prediction_error=.005)
        p=self.m.JumpRopeController(self.c);downs=[]
        for i in range(13):
            o=self.obs();o.update(hud_valid=False,hearts=None,rope_y=.40+i*.02*.4)
            downs.append(p.step(o,i*.02,downs[-1] if downs else False)['down'])
        self.assertTrue(p.tracking_established)
        self.assertEqual(p.jumps,1)
        self.assertTrue(any(downs))
        self.assertFalse(p.step(self.obs(False),.26,True)['down'])

class JumpRopeScreenshotTests(unittest.TestCase):
    def setUp(self):self.c,self.m,self.v=load(ROOT)
    def detect(self,name,scale=1):
        from modular_agent.perception.screen import load_image
        im=load_image(ROOT/'domains/hololive_dreams/data/jump_rope_samples'/name)
        if name=='reference.png':im=im[21:]
        if scale!=1:im=cv2.resize(im,None,fx=scale,fy=scale)
        h,w=im.shape[:2];l,t,r,b=self.c['roi']
        local=im[round(t*h):round(b*h),round(l*w):round(r*w)]
        if local.shape[1]>self.c['analysis_width']:
            local=cv2.resize(local,(self.c['analysis_width'],round(local.shape[0]*self.c['analysis_width']/local.shape[1])))
        self.v.reset()
        return self.v.detect(local,timestamp=0)
    def test_actual_overhead_and_low_rope_across_scales(self):
        for scale in (.75,1,1.5):
            for name,expected in [('reference.png',.069),('normal-0360.png',.491)]:
                with self.subTest(scale=scale,name=name):
                    o=self.detect(name,scale)
                    self.assertTrue(o['valid'],o)
                    if name=='reference.png':self.assertEqual(o['avatar_source'],'arrow')
                    self.assertIsNone(o['hearts'])
                    self.assertIsNone(o['hud_valid'])
                    self.assertEqual(o['probe_candidates'],[1,1])
                    self.assertAlmostEqual(o['rope_y'],expected,delta=.007)
    def test_intro_motion_does_not_claim_game_success(self):
        o=self.detect('normal-0270.png')
        self.assertTrue(o['valid'])
        self.assertIsNone(o['hud_valid'])
        self.assertIsNone(o['hearts'])
        self.assertIsNone(o['terminal'])
    def test_loading_screen_is_not_play(self):
        o=self.detect('normal-0060.png')
        self.assertIsNone(o['hud_valid'])
        self.assertFalse(o['valid'])
        self.assertIsNone(o['hearts'])

if __name__=='__main__':unittest.main()
