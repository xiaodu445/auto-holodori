import unittest
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT


class EdgeDedupTests(unittest.TestCase):
    def test_recorded_chord_does_not_gain_a_third_spanning_face(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/rhythm_samples/edge_duplicate_20261020.jpg'))
        self.assertIsNotNone(image)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(image,0)
        # Two genuine small yellow heads, plus an erroneous edge-based box
        # covering both in the original failure. Includes the frame that
        # created tracks #1641 and #1642.
        for lo,hi in ((.060,.070),(.205,.220),(.290,.305)):
            row=[n for n in notes if n.color=='yellow' and lo<n.center[1]<hi]
            self.assertEqual(len(row),2,(lo,[(n.center,n.width) for n in row]))

    def test_mock_spanning_edge_rejected_for_both_colours(self):
        c=dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))
        for hue in (28,60):
            hsv=np.zeros((540,960,3),np.uint8)
            for x in (350,480):cv2.rectangle(hsv,(x,145),(x+120,164),(hue,190,245),-1)
            v=m.RhythmVision(c)
            # Border pairing can span a narrow real gap. Even high average
            # colour coverage must not outweigh the two independent faces.
            v.face_edges=lambda image,field:[(350,145,251,20)]
            notes=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertEqual(len(notes),2)
            self.assertTrue(all(n.width*960<125 for n in notes))

    def test_supplemental_border_variants_are_not_two_notes(self):
        c=dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(420,85),(510,245),(28,190,225),-1)
        cv2.rectangle(hsv,(400,145),(535,164),(28,190,255),-1)
        v=m.RhythmVision(c)
        v.face_edges=lambda image,field:[(400,145,136,20),(402,146,132,18)]
        notes=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        row=[n for n in notes if abs(n.center[1]-155/540)<.01]
        self.assertEqual(len(row),1)

    def test_nearby_same_column_heads_remain_two(self):
        c=dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))
        hsv=np.zeros((540,960,3),np.uint8)
        for y in (145,170):cv2.rectangle(hsv,(400,y),(535,y+19),(28,190,245),-1)
        notes=m.RhythmVision(c).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertEqual(len(notes),2)
        self.assertEqual(len({n.lane for n in notes}),1)


if __name__=='__main__':unittest.main()
