import unittest
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT

class CrossRibbonTests(unittest.TestCase):
    def test_real_colour_crossing_is_not_end(self):
        im=cv2.imread(str(ROOT/'domains/hololive_dreams/data/rhythm_samples/cross_ribbon_20261020.jpg'))
        self.assertIsNotNone(im)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(im,0)
        heads=[n for n in notes if n.color=='yellow' and .50<n.center[0]<.65 and .43<n.center[1]<.51]
        self.assertEqual(len(heads),1)
        self.assertNotEqual(heads[0].kind,'slide_end')

    def test_real_wide_green_one_d_no_f(self):
        im=cv2.imread(str(ROOT/'domains/hololive_dreams/data/rhythm_samples/wide_fragment_20261020.jpg'))
        self.assertIsNotNone(im)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(im,0)
        row=[n for n in notes if n.color=='green' and .34<n.center[1]<.38 and n.center[0]<.5]
        self.assertEqual(len(row),1)
        self.assertEqual(row[0].lane,1)

    def test_different_colour_above_blocks_false_end(self):
        c=dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))
        for hue,up in ((28,60),(60,28)):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(400,85),(520,144),(up,150,170),-1)
            cv2.rectangle(hsv,(400,162),(520,225),(hue,150,170),-1)
            cv2.rectangle(hsv,(400,145),(520,160),(hue,190,245),-1)
            ns=m.RhythmVision(c).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertTrue(ns);self.assertTrue(all(n.kind!='slide_end' for n in ns))

if __name__=='__main__':unittest.main()
