import unittest
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT


class ChordFaceTests(unittest.TestCase):
    def config(self):
        return dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1))

    def test_real_connected_faces_are_two_correctly_sized_notes(self):
        path=ROOT/'domains/hololive_dreams/data/rhythm_samples/chord_link_20261019.jpg'
        image=cv2.imread(str(path));self.assertIsNotNone(image)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(image,0)
        pair=[n for n in notes if n.color=='blue' and .27<n.center[1]<.32]
        self.assertEqual(len(pair),2)
        self.assertEqual({n.lane for n in pair},{1,3})
        for n in pair:self.assertLess(n.width*960,85)

    def test_one_two_pixel_connector_not_a_note_or_merged_face(self):
        for thickness in (1,2):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(100,152),(860,151+thickness),(98,190,245),-1)
            for x in (350,510):cv2.rectangle(hsv,(x,145),(x+100,161),(98,190,245),-1)
            notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertEqual(len(notes),2)
            self.assertTrue(all(98<n.width*960<105 for n in notes))

    def test_wide_bar_remains_one_bar(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(150,145),(800,161),(98,190,245),-1)
        notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertEqual(len(notes),1);self.assertGreater(notes[0].width,.65)

    def test_genuine_two_pixel_far_face_is_preserved(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(458,43),(481,44),(98,190,245),-1)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertTrue(any(n.color=='blue' and n.center[1]<.16 for n in notes))

    def test_default_no_longer_changes_input_column(self):
        c=m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held'))
        self.assertEqual(c.c['key_lookahead_ms'],0)
        left,right=m.field_edges(c.c,.4)
        first=dict(id=1,lane=3,x=left+3.5/6*(right-left),y=.4,normalized_width=1/6,
            fired=False,locked=True,lock_until=1.1,arrival=1.,color='blue')
        other=dict(first,id=2,lane=2,x=left+2.5/6*(right-left),arrival=1.03)
        c.tracks=[first,other]
        self.assertEqual(c.select_input_lane(first,1.,.9),3)
    def test_real_yellow_pair_separates_tap_from_slide_end(self):
        path=ROOT/'domains/hololive_dreams/data/rhythm_samples/yellow_pair_merge_20261020.jpg'
        image=cv2.imread(str(path));self.assertIsNotNone(image)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(image,0)
        pair=sorted([n for n in notes if n.color=='yellow' and .40<n.center[1]<.49],key=lambda n:n.center[0])
        self.assertEqual(len(pair),2)
        self.assertEqual([n.kind for n in pair],['tap','slide_end'])
        for n in pair:self.assertLess(n.width*960,155)
        # The endpoint may be suppressed, but the other head must still run.
        c=m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',input_offset_ms=0))
        c.decide(pair,0)
        c.decide(pair,.015);c.decide(pair,.03)
        head=next(t for t in c.tracks if t['kind']=='tap')
        head.update(locked=True,arrival=.1,lock_until=.135)
        c.poll(.05);decision=c.poll(.1)
        self.assertTrue(any(e.get('id')==head['id'] and 'arrival' in e for e in decision['events']))
        self.assertEqual(len([t for t in c.tracks if t.get('ignored_reason')=='slide_end']),1)
    def test_coloured_pair_gap_preserved_even_with_ribbon_on_one_side(self):
        for hue,colour in ((60,'green'),(28,'yellow')):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(535,163),(655,225),(hue,150,170),-1)
            for x in (400,535):cv2.rectangle(hsv,(x,145),(x+120,161),(hue,190,245),-1)
            notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            pair=sorted([n for n in notes if n.color==colour],key=lambda n:n.center[0])
            self.assertEqual(len(pair),2)
            self.assertEqual([n.kind for n in pair],['tap','slide_end'])
    def test_coloured_single_wide_face_remains_one(self):
        for hue in (60,28):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(160,145),(800,161),(hue,190,245),-1)
            notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertEqual(len(notes),1);self.assertGreater(notes[0].width,.65)


if __name__=='__main__':unittest.main()
