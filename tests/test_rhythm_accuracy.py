import importlib.util,sys,unittest
from pathlib import Path
import cv2,numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('accuracy_test_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class AccuracyTests(unittest.TestCase):
    def setUp(self):self.config=m.load_config(ROOT)
    def test_recorded_pink_arrow_and_effect_fragments(self):
        vision=m.RhythmVision(self.config)
        for name,expected in [('pink_auto_clean.jpg',3),('pink_auto_split.jpg',1),('pink_auto_effect.jpg',1)]:
            im=cv2.imdecode(np.fromfile(ROOT/'domains/hololive_dreams/data/rhythm_samples'/name,np.uint8),1)
            notes=[n for n in vision.detect(im,0) if n.color=='pink']
            self.assertEqual(len(notes),expected,name)
    def test_short_real_pink_bar_is_not_rejected_as_arrow(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(410,230),(490,250),(155,200,245),-1)
        cv2.polylines(hsv,[np.array([(430,212),(450,202),(470,212)],np.int32)],False,(155,200,245),6)
        notes=[n for n in m.RhythmVision(self.config).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0) if n.color=='pink']
        self.assertEqual(len(notes),1)
        self.assertAlmostEqual(notes[0].center[1],240/540,delta=.005)
    def test_two_real_nearby_pink_bars_remain_distinct(self):
        hsv=np.zeros((540,960,3),np.uint8)
        for y in (230,270):cv2.rectangle(hsv,(410,y),(490,y+18),(155,200,245),-1)
        notes=[n for n in m.RhythmVision(self.config).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0) if n.color=='pink']
        self.assertEqual(len(notes),2)
    def controller(self):
        config=dict(self.config,motion_curve={'power':1.,'offset':0.},near_blue_refinement=True,prediction_zone=[.26,.62])
        c=m.RhythmController(config)
        for i in range(23):c.decide([self.note(.35+1.2*i*.01)],i*.01)
        return c,next(t for t in c.tracks if t.get('locked'))
    def note(self,y,width_factor=1.,height_factor=1.):
        l,r=m.field_edges(self.config,y);return m.Note(2,'tap',(.45,y),.16*(r-l)*width_factor,.04*(r-l)*height_factor,1)
    def test_two_clean_near_frames_refine_only_once_confirmed(self):
        c,t=self.controller();target=t['arrival'];t['arrival']+=.004
        c.decide([self.note(.35+1.2*.23)],.23)
        self.assertAlmostEqual(t['arrival'],target+.004)
        c.decide([self.note(.35+1.2*.24)],.24)
        self.assertEqual(t['prediction_source'],'near_blue_refinement')
        self.assertAlmostEqual(t['arrival'],target,delta=.0001)
        self.assertEqual(len(c.poll(target+.001)['events']),1)
        self.assertEqual(c.poll(target+.002)['events'],[])
    def test_bad_shape_or_glow_never_overwrites_clock(self):
        for width,height,y in ((.4,1,.638),(1,2,.638),(1,1,.76)):
            c,t=self.controller();arrival=t['arrival']
            for now in (.23,.24,.25):c.decide([self.note(y,width,height)],now)
            self.assertEqual(t['arrival'],arrival)
    def test_near_updates_cannot_make_large_clock_jump(self):
        c,t=self.controller();t['arrival']+=.030;original=t['arrival']
        for now in (.23,.24,.25,.26):c.decide([self.note(.35+1.2*now)],now)
        self.assertEqual(t['arrival'],original)
    def test_near_refinement_is_disabled_by_default(self):
        config=m.load_config(ROOT)
        self.assertFalse(config.get('near_blue_refinement',False))
        c,t=self.controller();c.c.pop('near_blue_refinement');original=t['arrival']
        for now in (.23,.24,.25,.26):c.decide([self.note(.35+1.2*now)],now)
        self.assertEqual(t['arrival'],original)
        self.assertNotEqual(t['prediction_source'],'near_blue_refinement')
    def test_shifted_boundary_freezes_unconfirmed_tracks_too(self):
        c=m.RhythmController(self.config)
        c.decide([m.Note(2,'tap',(.45,.50),.08,.02,1)],0.)
        t=c.tracks[0];before=list(t['history'])
        for i in range(1,6):c.decide([m.Note(2,'tap',(.45,.55+i*.005),.08,.02,1)],i*.01)
        self.assertEqual(list(t['history']),before)
        self.assertIsNone(t['arrival'])
        self.assertEqual(c.poll(.2)['events'],[])
    def test_shifted_zone_still_predicts_actual_hit_and_learns_grid(self):
        config=dict(self.config,motion_curve={'power':1.,'offset':0.})
        self.assertEqual(config['prediction_zone'],[.22,.54])
        self.assertAlmostEqual(config['hit_line_y'],573/711)
        c=m.RhythmController(config);target=.5
        for i in range(35):
            now=i*.01;y=config['hit_line_y']+(now-target)*1.2
            c.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
        self.assertEqual(len(c.grid.arrivals),1)
        self.assertAlmostEqual(c.tracks[0]['arrival'],target)
        self.assertEqual(len(c.poll(target+.001)['events']),1)

if __name__=='__main__':unittest.main()
