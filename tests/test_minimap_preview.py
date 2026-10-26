import unittest
import numpy as np
from modular_agent.realtime.minimap_preview import MapPreview
from modular_agent.realtime.patrol import overlay
from modular_agent.domains.hololive_dreams.patrol import Position


class PreviewTests(unittest.TestCase):
    def test_native_pixels_survive_window_resize_and_close(self):
        image = np.zeros((780,676,3),np.uint8)
        window = MapPreview('hidden test',image,visible=False)
        try:
            self.assertEqual((window.photo.width(),window.photo.height()),(676,780))
            window.root.geometry('400x300');window.show(image)
            self.assertEqual((window.photo.width(),window.photo.height()),(676,780))
            self.assertEqual(tuple(map(float,window.canvas.cget('scrollregion').split())),(0,0,676,780))
        finally:window.close()
        self.assertFalse(window.show(image))

    def test_rejected_candidate_does_not_draw_position_marker(self):
        image = np.zeros((180,180,3),np.uint8)
        canvas = overlay(image,Position(100,100,0,False,.5,reason='low_similarity'))
        self.assertFalse(canvas[85:116,85:116].any())
        accepted = overlay(image,Position(100,100,0,True,.95))
        self.assertTrue(accepted[85:116,85:116].any())


if __name__=='__main__':unittest.main()
