import json,unittest
from collections import deque
from test_rhythm_grid import m, ROOT


class DiscreteTrackingTests(unittest.TestCase):
    def config(self):return dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',input_offset_ms=75)

    def test_exact_boundary_lane_stable_under_half_pixel_jitter(self):
        c=self.config();vision=m.RhythmVision(c);left,right=m.field_edges(c,.4)
        lanes={vision.lane_for(.5+delta,.4,(right-left)*.5) for delta in (-.5/960,0,.5/960)}
        self.assertEqual(lanes,{2})

    def test_recorded_boundary_observations_produce_one_track_one_press(self):
        p=ROOT/'domains/hololive_dreams/data/rhythm_samples/boundary_duplicate_20261020.json'
        data=json.loads(p.read_text(encoding='utf-8'));c=m.RhythmController(self.config())
        previous=0;heads=[];max_tracks=0
        for t,lane,x,y,width,height in data['observations']:
            for step in range(int(previous*1000)+1,int(t*1000)):
                heads.extend(e for e in c.poll(step/1000)['events'] if 'arrival' in e)
            d=c.decide([m.Note(lane,'tap',(x,y),width,height,1.,'yellow')],t)
            heads.extend(e for e in d['events'] if 'arrival' in e)
            max_tracks=max(max_tracks,len(c.tracks));previous=t
        for step in range(int(previous*1000)+1,801):heads.extend(e for e in c.poll(step/1000)['events'] if 'arrival' in e)
        self.assertEqual(c.sequence,1);self.assertEqual(max_tracks,1);self.assertEqual(len(heads),1)

    def duplicate(self,identity,lane,arrival,last=.2,fired=False):
        return dict(id=identity,lane=lane,color='yellow',kind='tap',x=.5,y=.3,last=last,
            history=deque(maxlen=8),locked=True,lock_until=1.1,arrival=arrival,fired=fired,
            prediction_source='middle_zone',cell_span=(3,9),velocity=1.)

    def test_already_split_adjacent_lane_tracks_merge_before_dispatch(self):
        c=m.RhythmController(self.config());c.tracks=[self.duplicate(1,3,1.),self.duplicate(2,2,1.02,last=.21)]
        events=c.merge_duplicates(.21)
        self.assertEqual(len(c.tracks),1);self.assertEqual(events[0]['type'],'duplicate_track_merged')

    def test_thirty_ms_repeated_notes_are_not_merged(self):
        c=m.RhythmController(self.config());c.tracks=[self.duplicate(1,3,1.),self.duplicate(2,2,1.03)]
        self.assertEqual(c.merge_duplicates(.2),[]);self.assertEqual(len(c.tracks),2)

    def test_coobserved_chord_and_different_spans_are_not_merged(self):
        c=m.RhythmController(self.config());c.tracks=[self.duplicate(1,3,1.),self.duplicate(2,2,1.)]
        c.distinct_pairs.add((1,2));self.assertFalse(c.merge_duplicates(.2))
        c.distinct_pairs.clear();c.tracks[1]['cell_span']=(4,8)
        self.assertFalse(c.merge_duplicates(.2))

    def test_already_pressed_duplicate_cannot_schedule_another_head(self):
        c=m.RhythmController(self.config());c.tracks=[self.duplicate(1,3,1.,fired=True),self.duplicate(2,2,1.01)]
        c.merge_duplicates(.2)
        self.assertTrue(c.tracks[0]['fired']);self.assertFalse(c.poll(.95)['events'])


if __name__=='__main__':unittest.main()
