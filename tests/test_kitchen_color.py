import unittest
import cv2
import numpy as np
from modular_agent.realtime.kitchen_color import detect,average_hsv


def image():
    hsv=np.zeros((100,120,3),np.uint8)
    hsv[:,:,2]=30
    hsv[20:50,30:60]=[179,230,220]
    return cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)


def profile():
    return dict(roi=[.1,.1,.9,.9],classes=dict(red=dict(samples=[[1,230,220]],tolerance=[4,20,20],min_area=10,min_radius=2)))


class ColorTests(unittest.TestCase):
    def test_red_hue_wrap_and_roi_coordinate_restoration(self):
        items,stats=detect(image(),profile())
        self.assertEqual(len(items),1)
        self.assertTrue(30<=items[0]['x']<60)
        self.assertTrue(20<=items[0]['y']<50)
        self.assertGreater(items[0]['color_margin_px'],10)

    def test_conflicting_classes_are_not_silently_assigned(self):
        p=profile();p['classes']['other']=p['classes']['red'].copy()
        items,stats=detect(image(),p)
        self.assertEqual(items,[])
        self.assertGreater(stats['ambiguous_pixels'],0)

    def test_outside_roi_and_small_noise_ignored(self):
        p=profile();p['roi']=[.6,.6,1,1]
        self.assertEqual(detect(image(),p)[0],[])
        hsv=np.zeros((100,120,3),np.uint8);hsv[35,40]=[0,230,220]
        self.assertEqual(detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),profile())[0],[])

    def test_empty_profile_and_invalid_roi(self):
        self.assertEqual(detect(image(),dict(classes={}))[0],[])
        with self.assertRaises(ValueError):detect(image(),dict(roi=[1,0,0,1]))

    def test_click_point_is_on_matching_color(self):
        hsv=np.zeros((100,120,3),np.uint8)
        hsv[20:60,30:70]=[0,230,220];hsv[30:50,40:60]=[90,230,220]
        items,_=detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),profile())
        self.assertEqual(len(items),1)
        self.assertEqual(int(hsv[items[0]['y'],items[0]['x'],0]),0)


class AverageColorTests(unittest.TestCase):
    def test_red_average_wraps_at_hue_seam(self):
        hsv=np.array([[[179,255,220],[1,255,220]]],np.uint8)
        color=average_hsv(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR))
        self.assertLess(min(color[0],180-color[0]),2)

    def test_local_average_reduces_single_pixel_noise(self):
        img=np.full((21,21,3),(0,0,220),np.uint8);img[10,10]=[255,255,255]
        color=average_hsv(img,5)[10,10]
        self.assertGreater(color[1],230)
        with self.assertRaises(ValueError):average_hsv(img,4)

    def test_average_rule_matches_region_not_individual_pixels(self):
        hsv=np.zeros((40,40,3),np.uint8);hsv[:]=[0,200,100]
        hsv[::2,:,2]=200
        img=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        p=dict(roi=[0,0,1,1],average_kernel=5,classes=dict(red=dict(
            samples=[[0,200,150]],tolerance=[3,8,15],min_area=10,min_radius=1)))
        self.assertTrue(detect(img,p)[0])
        p['average_kernel']=1
        self.assertEqual(detect(img,p)[0],[])
