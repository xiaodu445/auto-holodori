import unittest,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'learning/kitchen_yolo'))
from prepare_combined import sampling_copies,rotate_square

class SingleInstanceAugmentationTests(unittest.TestCase):
    def test_sampling_does_not_repeat_validation(self):
        for split,count,expected in [('train',1,4),('train',2,2),('train',12,1),('val',1,1)]:
            entry=dict(split=split,frame=dict(points=[{}]*count))
            self.assertEqual(sampling_copies(entry,2,4),expected)
    def test_quarter_turn_transforms_box_and_discrete_click_point(self):
        image=np.zeros((4,4,3),np.uint8);image[1,1]=255
        rotated,rows=rotate_square(image,[[3,.5,.25,.5,.5,.25,.25,2]],1)
        self.assertTrue((rotated[1,2]==255).all())
        np.testing.assert_allclose(rows[0],[3,.75,.5,.5,.5,.5,.25,2])
    def test_four_turns_preserve_original_geometry_and_pixels(self):
        image=np.arange(48,dtype=np.uint8).reshape(4,4,3);rows=[[1,.4,.6,.2,.4,.4,.6,2]]
        out,labels=rotate_square(image,rows,4)
        np.testing.assert_array_equal(out,image);np.testing.assert_allclose(labels,rows)
