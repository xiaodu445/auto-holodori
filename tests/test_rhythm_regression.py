import importlib.util
from pathlib import Path
import sys
import unittest
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rhythm_regression',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class RhythmRegression(unittest.TestCase):
    def setUp(self):
        self.c=m.load_config(ROOT)
        # Existing fixtures explicitly simulate screen-linear motion.
        self.c['motion_curve']={'power':1.,'offset':0.}
        # Original synthetic fixtures exercise the original .26-.62 band.
        # Shifted production boundaries have dedicated accuracy regressions.
        self.c['prediction_zone']=[.26,.62]
        self.c['recognition_end_y']=.825  # Legacy geometry/shape fixtures, not production ROI.

    def test_curve_inverse_and_real_profile_acceleration(self):
        curve=m.MotionCurve(m.load_config(ROOT))
        for y in (.06,.26,.40,.60,.806):
            self.assertAlmostEqual(float(curve.position(curve.phase(y))),y)
        self.assertGreater(curve.derivative(.40)/curve.derivative(.60),1.3)

    def test_learned_curve_early_dropout_and_scheduler(self):
        config=m.load_config(ROOT);curve=m.MotionCurve(config)
        arrival=1.;rate=1.5;hit=curve.phase(config['hit_line_y'])
        for cutoff in (.22,.40,.50,.60):
            c=m.RhythmController(config)
            for i in range(100):
                now=i*.01;y=float(curve.position(hit+rate*(now-arrival)))
                if .10<y<=cutoff:c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
            if cutoff<.26:
                self.assertTrue(any(t['arrival'] is not None for t in c.tracks))
                self.assertEqual(c.poll(arrival)['events'],[])
            else:
                locked=[t for t in c.tracks if t.get('locked')]
                self.assertEqual(len(locked),1)
                self.assertAlmostEqual(locked[0]['arrival'],arrival,delta=.0001)
                self.assertEqual(len(c.poll(arrival+.001)['events']),1)
                self.assertEqual(c.poll(arrival+.002)['events'],[])

    def test_curve_predicts_acceleration_for_association(self):
        curve=m.MotionCurve(m.load_config(ROOT));track={'last':0.,'y':.4,'phase_rate':1.5,'velocity':1.5/curve.derivative(.4)}
        projected=curve.predict(track,.1)
        self.assertGreater(projected,.4+track['velocity']*.1)
        self.assertAlmostEqual(float(curve.phase(projected)-curve.phase(.4)),.15)

    def test_curve_filter_retains_real_acceleration_rejects_effect(self):
        config=m.load_config(ROOT);c=m.RhythmController(config);curve=c.motion
        hit=curve.phase(config['hit_line_y']);arrival=.8;rate=1.5
        original=None
        for i in range(80):
            now=i*.01;y=float(curve.position(hit+rate*(now-arrival)))
            if not .10<y<.61:continue
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
            if y>.4 and original is None:
                original=next(t for t in c.tracks if t.get('locked'))
                previous=list(original['history'])
                c.decide([m.Note(2,'tap',(.45,y+.035),.08,.02,1)],now+.001)
                self.assertEqual(list(original['history']),previous)
                self.assertEqual(original['prediction_source'],'rejected_observation')
        self.assertIsNotNone(original)
        self.assertGreater(original['y'],config['prediction_zone'][1]-.03)
        self.assertAlmostEqual(original['arrival'],arrival,delta=.001)
        self.assertEqual(len(c.poll(arrival+.001)['events']),1)
    def test_calibrated_grid_excludes_decorative_outer_strip(self):
        left,right=m.field_edges(self.c,573/711)
        self.assertAlmostEqual(left*1264,122,delta=.1)
        self.assertAlmostEqual(right*1264,1142,delta=.1)
        vision=m.RhythmVision(self.c)
        self.assertIsNone(vision.lane_for(90/1264,573/711))
        for lane in range(6):self.assertEqual(vision.lane_for((207+170*lane)/1264,573/711),lane)
    def test_colored_wide_bars(self):
        for hue in (60,28):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(175,365),(785,386),(hue,180,245),-1)
            notes=m.RhythmVision(self.c).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertTrue(any(n.color!='blue' and n.width>.6 and n.kind=='tap' for n in notes))

    def test_occlusion_coasts_to_deadline_once(self):
        c=m.RhythmController(self.c)
        for i in range(50):
            now=i*.01;y=.804+(now-.65)*.8
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        events=[]
        for i in range(50,85):events+=c.decide([],i*.01)['events']
        self.assertEqual(len(events),1)
        self.assertAlmostEqual(events[0]['time'],.65,delta=.015)

    def test_expired_occlusion_not_clicked(self):
        c=m.RhythmController(self.c)
        for i in range(30):
            now=i*.01;y=.804+(now-.7)*.8
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        self.assertEqual(c.poll(.9)['events'],[])

    def test_middle_effect_outlier_does_not_poison_history(self):
        c=m.RhythmController(self.c)
        for i in range(30):
            now=i*.01;y=self.c['hit_line_y']+(now-.65)*.8
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        track=next(t for t in c.tracks if t.get('locked'))
        previous=list(track['history']);arrival=track['arrival']
        y=track['y']+.008+.035
        c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],.30)
        self.assertEqual(list(track['history']),previous)
        self.assertEqual(track['prediction_source'],'rejected_observation')
        self.assertEqual(track['arrival'],arrival)
        for i in range(31,42):
            now=i*.01;y=self.c['hit_line_y']+(now-.65)*.8
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        self.assertAlmostEqual(track['arrival'],.65,delta=.003)
        self.assertEqual(len(c.poll(.651)['events']),1)

    def test_poll_fires_between_captures_and_releases(self):
        c=m.RhythmController(self.c)
        for i in range(6):
            now=i*.01;y=self.c['hit_line_y']+(now-.15)*2
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        self.assertIn('f',c.poll(.151)['keys'])
        self.assertFalse(c.poll(.19)['keys'])
        self.assertEqual(c.poll(.20)['events'],[])

    def test_known_bpm_only_tiny_correction(self):
        grid=m.BeatGrid(16,150);grid.observe(1.)
        self.assertAlmostEqual(grid.nearest(1.102),1.1)
        self.assertAlmostEqual(grid.nearest(1.12),1.12)
        for _ in range(20):grid.observe(1.)
        self.assertEqual(len(grid.arrivals),1)
    def test_user_wide_blue_bar(self):
        image=cv2.imdecode(np.fromfile(ROOT/'domains/hololive_dreams/data/rhythm_samples/wide_blue_report.png',np.uint8),1)[38:]
        notes=m.RhythmVision(self.c).detect(image,0)
        wide=[n for n in notes if n.color=='blue' and n.width>.30]
        self.assertEqual(len(wide),1)
        self.assertEqual(wide[0].kind,'tap')
        self.assertAlmostEqual(wide[0].center[1],.63,delta=.02)
    def test_nearly_full_field_blue_bar(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(175,365),(785,386),(98,180,245),-1)
        notes=m.RhythmVision(self.c).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertEqual(len(notes),1)
        self.assertGreater(notes[0].width,.6)
        self.assertEqual(notes[0].kind,'tap')
    def test_reference_images_reject_scenery(self):
        for index,expected in enumerate((3,2,3,2),1):
            image=cv2.imdecode(np.fromfile(ROOT/f'domains/hololive_dreams/data/rhythm_samples/reference_{index}.png',np.uint8),cv2.IMREAD_COLOR)[38:]
            notes=m.RhythmVision(self.c).detect(image,0)
            notes=[n for n in notes if n.color=='blue']
            middle=[n for n in notes if n.center[1]>=.18]
            self.assertEqual(len(middle),expected)
            self.assertTrue(all(n.center[1]<.769 for n in notes))
    def test_static_bar_cannot_schedule_input(self):
        controller=m.RhythmController(self.c)
        for i in range(100):
            decision=controller.decide([m.Note(2,'tap',(.45,.70),.08,.02,1)],i*.01)
            self.assertFalse(decision['keys'])
            self.assertFalse(decision['events'])
    def test_same_lane_repeats_and_chord(self):
        controller=m.RhythmController(self.c); events=[]
        for i in range(120):
            now=i*.01; notes=[]
            for arrival,lane in ((.7,2),(1.,2),(.7,4)):
                y=.804+(now-arrival)*.8
                if .2<y<.769: notes.append(m.Note(lane,'tap',(.45,y),.08,.02,1))
            events+=controller.decide(notes,now)['events']
        self.assertEqual(sorted(e['key'] for e in events),['f','f','k'])
        self.assertFalse(controller.decide([],1.3)['keys'])
    def test_dark_background_rejected(self):
        image=np.full((540,960,3),(160,110,40),np.uint8)
        self.assertEqual(m.RhythmVision(self.c).detect(image,0),[])

    def test_tail_required_for_hold(self):
        v=m.RhythmVision(self.c)
        for color,hue in [('green',60),('yellow',28)]:
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(370,295),(450,310),(hue,180,245),-1)
            notes=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            bars=[n for n in notes if n.color==color]
            self.assertTrue(bars)
            self.assertTrue(all(n.kind=='tap' for n in bars))
            cv2.rectangle(hsv,(385,210),(435,294),(hue,120,180),-1)
            notes=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),.01)
            self.assertTrue(any(n.color==color and n.kind=='hold' and n.tail for n in notes))

    def test_hold_middle_route_and_safety_release(self):
        for color in ('green','yellow'):
            c=m.RhythmController(self.c);started=False
            for i in range(90):
                now=i*.01;y=.804+(now-.7)*.8
                notes=[m.Note(2,'hold',(.45,y),.08,.02,1.,color,((.45,y-.05,.08),(.53,y-.1,.08)))] if .2<y<.769 else []
                paths=[dict(color=color,lane=2 if now<.8 else 3)] if .68<now else []
                d=c.decide(notes,now,paths)
                if .72<now<.78:self.assertIn('f',d['keys']);started=True
            self.assertTrue(started)
            self.assertIn('j',d['keys'])
            self.assertIn('j',c.decide([],1.2,[])['keys'])
            self.assertFalse(c.decide([],21.,[])['keys'])

    def test_far_small_note(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(475,58),(498,61),(98,180,245),-1)
        notes=m.RhythmVision(self.c).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertTrue(any(n.color=='blue' and n.center[1]<.18 for n in notes))

    def test_red_zone_bad_observations_do_not_destroy_clock(self):
        c=m.RhythmController(self.c)
        for i in range(40):
            now=i*.01;y=self.c['hit_line_y']+(now-.65)*.8
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        track=c.tracks[0];self.assertTrue(track['locked']);arrival=track['arrival']
        for i in range(40,65):
            now=i*.01
            c.decide([m.Note(2,'tap',(.45,.7+(i%2)*.025),.08,.02,1)],now)
        self.assertAlmostEqual(track['arrival'],arrival,delta=.015)
        events=c.poll(.652)['events'];self.assertEqual(len(events),1)

    def test_pink_trial_switch(self):
        for enabled in (False,True):
            c=m.RhythmController({**self.c,'pink_tap_trial':enabled});events=[]
            for i in range(90):
                now=i*.01;y=self.c['hit_line_y']+(now-.65)*.8
                notes=[m.Note(2,'pink_trial',(.45,y),.15,.02,1,'pink')] if .1<y<.769 else []
                events+=c.decide(notes,now)['events']
            self.assertEqual(len(events),1 if enabled else 0)

    def test_pink_from_reference(self):
        image=cv2.imdecode(np.fromfile(ROOT/'domains/hololive_dreams/data/rhythm_samples/reference_2.png',np.uint8),1)[38:]
        notes=m.RhythmVision(self.c).detect(image,0)
        # This reference also has a green ribbon below the pink face: the
        # user clarified that these are endpoints, not standalone flicks.
        self.assertTrue(any(n.color=='pink' and n.kind=='slide_end' and n.appearance_score is not None for n in notes))

if __name__=='__main__': unittest.main()
