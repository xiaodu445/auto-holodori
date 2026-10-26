import json,unittest
from pathlib import Path
import cv2
import numpy as np
from test_rhythm_grid import m, ROOT


class SlideEndTests(unittest.TestCase):
    def config(self, **changes):
        c=dict(m.load_config(ROOT),geometry=dict(top_y=0,top_left=0,top_right=1,hit_left=0,hit_right=1),
            input_mode='all-held',release_scope='target',input_offset_ms=10,dense_gap_ms=100)
        c.update(changes);return c

    def image(self,hue=60,above=False,below=False,thin=False):
        hsv=np.zeros((540,960,3),np.uint8)
        if above:cv2.rectangle(hsv,(400,85),(520,144),(hue,150,170),-1)
        if below:cv2.rectangle(hsv,(458 if thin else 400,162),(463 if thin else 520,225),(hue,150,170),-1)
        cv2.rectangle(hsv,(400,145),(520,160),(hue,190,245),-1)
        return cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)

    def test_down_only_is_end_up_only_still_head_and_both_preserved(self):
        for hue,color in ((60,'green'),(28,'yellow')):
            for above,below,kind in ((False,True,'slide_end'),(True,False,'hold'),(True,True,'hold'),(False,False,'tap')):
                with self.subTest(color=color,above=above,below=below):
                    notes=m.RhythmVision(self.config()).detect(self.image(hue,above,below),0)
                    notes=[n for n in notes if n.color==color]
                    self.assertEqual(len(notes),1);self.assertEqual(notes[0].kind,kind)

    def test_thin_downward_sparkle_is_not_end(self):
        notes=m.RhythmVision(self.config()).detect(self.image(below=True,thin=True),0)
        self.assertEqual([n.kind for n in notes if n.color=='green'],['tap'])
    def test_irregular_split_coloured_background_counts_as_end(self):
        image=self.image();hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        polygon=np.array([[400,163],[515,163],[430,178],[520,190],[400,210],[490,220]],np.int32)
        cv2.fillPoly(hsv,[polygon],(60,150,170))
        notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertTrue(any(n.kind=='slide_end' for n in notes))

    def test_disconnected_bar_below_does_not_become_ribbon(self):
        image=self.image()
        cv2.rectangle(image,(400,210),(520,225),(0,245,0),-1)
        notes=m.RhythmVision(self.config()).detect(image,0)
        self.assertTrue(notes);self.assertTrue(all(n.kind=='tap' for n in notes))

    def test_user_crop_is_recognized_as_end(self):
        path=ROOT/'domains/hololive_dreams/data/rhythm_samples/slide_end_user_20261019.png'
        crop=cv2.imread(str(path));self.assertIsNotNone(crop)
        canvas=np.zeros((540,960,3),np.uint8)
        canvas[90:90+crop.shape[0],270:270+crop.shape[1]]=crop
        notes=m.RhythmVision(self.config()).detect(canvas,0)
        faces=[n for n in notes if n.color=='green' and n.width>.15]
        self.assertTrue(faces);self.assertTrue(all(n.kind=='slide_end' for n in faces))
    def test_recorded_yellow_glow_below_wide_tap_is_not_end(self):
        path=ROOT/'domains/hololive_dreams/data/rhythm_samples/false_slide_end_glow_20261020.jpg'
        image=cv2.imread(str(path));self.assertIsNotNone(image)
        notes=m.RhythmVision(m.load_config(ROOT)).detect(image,0)
        faces=[n for n in notes if n.color=='yellow' and n.width>.4]
        self.assertEqual(len(faces),1)
        self.assertEqual(faces[0].kind,'tap')
    def test_short_window_rejects_glow_with_uncoloured_gap(self):
        image=self.image(hue=28);hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        cv2.rectangle(hsv,(380,173),(540,225),(28,150,170),-1)
        notes=m.RhythmVision(self.config()).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        self.assertEqual([n.kind for n in notes if n.color=='yellow'],['tap'])
    def test_sparse_broad_sparkles_do_not_qualify_as_background(self):
        v=m.RhythmVision(self.config());mask=np.zeros((540,960),np.uint8)
        mask[163:165,400:521]=255
        self.assertFalse(v.side_colour(mask,400,145,121,16,1))

    def note(self,kind):return m.Note(2,kind,(.46,.30),.125,.03,1.,'green')

    def test_end_never_produces_input_in_any_input_strategy(self):
        for mode,scope in (('normal','target'),('all-held','target'),('all-held','all')):
            c=m.RhythmController(self.config(input_mode=mode,release_scope=scope))
            d=c.decide([self.note('slide_end')],.8)
            self.assertFalse(d['events'])
            c.decide([self.note('slide_end')],.815)
            d=c.decide([self.note('slide_end')],.83)
            self.assertEqual([e['type'] for e in d['events']],['ignored_slide_end'])
            self.assertEqual(c.tracks[0]['ignored_reason'],'slide_end')
            for now in (.9,.95,.99,1.01):
                d=c.poll(now)
                self.assertFalse(d['events'])
                self.assertEqual(d['keys'],set(c.keys) if mode=='all-held' else set())

    def test_prior_ambiguous_track_pending_repress_is_cancelled(self):
        for scope in ('target','all'):
            c=m.RhythmController(self.config(release_scope=scope,dense_gap_ms=0))
            c.decide([self.note('tap')],.8)
            t=c.tracks[0];t.update(locked=True,lock_until=1.035,arrival=1.,stable_fit_count=3)
            c.poll(.95)
            self.assertTrue(c.held_pending or c.all_release_batch)
            d=c.decide([self.note('slide_end')],.951)
            c.decide([self.note('slide_end')],.966)
            d=c.decide([self.note('slide_end')],.981)
            self.assertFalse(c.held_pending);self.assertIsNone(c.all_release_batch)
            self.assertTrue(any(e.get('type')=='ignored_slide_end' for e in d['events']))
            self.assertFalse(any('arrival' in e for e in c.poll(.99)['events']))

    def test_later_note_same_colour_and_lane_still_presses(self):
        c=m.RhythmController(self.config())
        c.decide([self.note('slide_end')],.8)
        c.decide([self.note('slide_end')],.815)
        c.decide([self.note('slide_end')],.83)
        new=m.Note(2,'tap',(.46,.2),.125,.03,1.,'green')
        c.decide([new],.9)
        self.assertEqual(len(c.tracks),2)
        t=c.tracks[-1];t.update(locked=True,lock_until=1.035,arrival=1.,stable_fit_count=3)
        self.assertNotIn('f',c.poll(.95)['keys'])
        d=c.poll(.99)
        self.assertTrue(any(e.get('id')==t['id'] and 'arrival' in e for e in d['events']))
    def test_single_or_two_end_votes_do_not_permanently_ignore(self):
        for count in (1,2):
            c=m.RhythmController(self.config())
            for i in range(count):c.decide([self.note('slide_end')],.8+i*.015)
            t=c.tracks[0];self.assertFalse(t.get('ignored_reason'))
            c.decide([self.note('tap')],.845)
            self.assertEqual(t['end_votes'],0)
            self.assertEqual(t['kind'],'tap')
    def test_confirmed_normal_head_rejects_late_tail_override(self):
        c=m.RhythmController(self.config());c.decide([self.note('tap')],.8)
        t=c.tracks[0];t.update(locked=True,arrival=1.,lock_until=1.035,head_observations=6,head_confirmed=True)
        for i in range(4):
            note=self.note('slide_end');c.decide([note],.9+i*.015)
            self.assertEqual(note.kind,'tap');self.assertEqual(note.raw_kind,'slide_end')
        self.assertFalse(t.get('ignored_reason'));self.assertFalse(t['fired'])
        d=c.poll(.99);self.assertTrue(any('arrival' in e for e in d['events']))
    def test_recorded_1326_late_colour_hit_preserves_press(self):
        p=ROOT/'domains/hololive_dreams/data/rhythm_samples/late_tail_override_20261020.json'
        data=json.loads(p.read_text(encoding='utf-8'));c=m.RhythmController(m.load_config(ROOT)|dict(input_mode='all-held',release_scope='target'))
        events=[]
        for t,kind,lane,x,y,w,h in data['observations']:
            d=c.decide([m.Note(lane,kind,(x,y),w,h,1.,'yellow')],t);events.extend(d['events'])
        for i in range(466,801):events.extend(c.poll(i/1000)['events'])
        self.assertFalse(any(e.get('type')=='ignored_slide_end' for e in events))
        self.assertTrue(any(e.get('type')=='slide_end_rejected_confirmed_head' for e in events))
        self.assertEqual(len([e for e in events if 'arrival' in e]),1)


if __name__=='__main__':unittest.main()
