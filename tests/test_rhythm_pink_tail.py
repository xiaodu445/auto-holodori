import unittest
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT

class PinkTailTests(unittest.TestCase):
    def config(self):
        return dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1),input_mode='all-held')

    def notes(self,above=False,below=False,hue=60,thin=False):
        hsv=np.zeros((540,960,3),np.uint8)
        if above:cv2.rectangle(hsv,(400,85),(520,144),(hue,150,170),-1)
        if below:cv2.rectangle(hsv,(458 if thin else 400,166),(463 if thin else 520,225),(hue,150,170),-1)
        cv2.rectangle(hsv,(400,145),(520,164),(155,190,245),-1)
        cv2.polylines(hsv,[np.array([[425,123],[460,108],[495,123]],np.int32)],False,(155,190,245),5)
        return [n for n in m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0) if n.color=='pink']

    def test_pink_face_can_end_either_ribbon_colour(self):
        for hue in (60,28):self.assertEqual([n.kind for n in self.notes(below=True,hue=hue)],['slide_end'])

    def test_standalone_upstream_and_two_sided_pink_still_press(self):
        for above,below in ((False,False),(True,False),(True,True)):
            self.assertEqual([n.kind for n in self.notes(above,below)],['pink_trial'])

    def test_thin_effect_not_a_tail(self):
        self.assertEqual([n.kind for n in self.notes(below=True,thin=True)],['pink_trial'])

    def test_confirmed_pink_tail_generates_no_head_input(self):
        c=m.RhythmController(self.config())
        events=[]
        for i in range(3):events+=c.decide(self.notes(below=True),i*.015)['events']
        self.assertEqual(len(c.tracks),1)
        self.assertEqual(c.tracks[0].get('ignored_reason'),'slide_end')
        self.assertFalse(any('arrival' in e for e in events))

    def test_user_pink_face_over_green_ribbon(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/rhythm_samples/pink_tail_user_20261020.png'))
        self.assertIsNotNone(image)
        image=cv2.resize(image,None,fx=.5,fy=.5)
        canvas=np.zeros((540,960,3),np.uint8)
        canvas[20:20+image.shape[0],40:40+image.shape[1]]=image
        pink=[n for n in m.RhythmVision(self.config()).detect(canvas,0) if n.color=='pink']
        self.assertEqual([n.kind for n in pink],['slide_end'])

if __name__=='__main__':unittest.main()
