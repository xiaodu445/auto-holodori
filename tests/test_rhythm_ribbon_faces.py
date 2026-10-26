import unittest
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT


class RibbonFaceTests(unittest.TestCase):
    def config(self):
        return dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))

    def image(self,hue,face=True,y=145):
        hsv=np.zeros((540,960,3),np.uint8)
        # Bright, irregular ribbon is connected through the face, so its
        # connected-component height cannot represent the note thickness.
        points=np.array([[420,80],[510,80],[525,120],[510,190],[530,245],[420,245],[405,200],[430,120]],np.int32)
        cv2.fillPoly(hsv,[points],(hue,190,225))
        if face:cv2.rectangle(hsv,(400,y),(535,y+16),(hue,190,255),-1)
        return cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)

    def test_faces_survive_bright_irregular_ribbons_both_colours(self):
        for hue,col in ((60,'green'),(28,'yellow')):
            notes=m.RhythmVision(self.config()).detect(self.image(hue),0)
            faces=[n for n in notes if n.color==col and abs(n.center[1]-153/540)<.012]
            self.assertEqual(len(faces),1)
            self.assertGreater(faces[0].width*960,125)
            self.assertLess(faces[0].height*540,25)

    def test_ribbon_without_face_not_promoted_to_note(self):
        for hue in (60,28):
            self.assertEqual(m.RhythmVision(self.config()).detect(self.image(hue,False),0),[])

    def test_real_yellow_face_embedded_in_ribbon_recovered_once(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/rhythm_samples/ribbon_overlap_20261020.jpg'))
        self.assertIsNotNone(image)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(image,0)
        for x,y in ((.44,.21),(.609,.405)):
            self.assertEqual(len([n for n in notes if n.color=='yellow' and
                abs(n.center[0]-x)<.02 and abs(n.center[1]-y)<.015]),1)

    def test_lower_zone_is_still_excluded(self):
        notes=m.RhythmVision(self.config()).detect(self.image(28,y=340),0)
        self.assertFalse(any(n.center[1]>.54 for n in notes))

    def test_thin_horizontal_effects_not_promoted(self):
        hsv=np.zeros((540,960,3),np.uint8)
        for y in (150,151,170):cv2.line(hsv,(300,y),(650,y),(28,190,255),1)
        notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertEqual(notes,[])


if __name__=='__main__':unittest.main()
