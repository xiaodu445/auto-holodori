import unittest
from test_rhythm_grid import m, ROOT


class SequenceInputTests(unittest.TestCase):
    def controller(self, **overrides):
        config=dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',
            input_offset_ms=0,dense_gap_ms=0,release_lead_ms=60,key_lookahead_ms=100)
        config.update(overrides)
        return m.RhythmController(config)

    def track(self, c, identity, lane, arrival, geometry=False):
        track=dict(id=identity,lane=lane,color='blue',kind='tap',locked=True,
            lock_until=arrival+.035,arrival=arrival,last=arrival-.2,fired=False,
            prediction_source='middle_zone')
        if geometry:
            left,right=m.field_edges(c.c,.4)
            track.update(x=left+(lane+.5)*(right-left)/6,y=.4,normalized_width=1/6)
        return track

    def simulate(self,c,start=.9,end=1.15):
        edges=[];events=[];down=set()
        for step in range(round((end-start)*1000)+1):
            now=round(start+step/1000,6);d=c.poll(now)
            edges.extend((now,k,k in d['keys']) for k in sorted(down^d['keys']))
            down=set(d['keys']);events.extend(d['events'])
        return edges,events

    def test_thirty_ms_same_key_preserves_down_and_up_windows(self):
        for dense in (0,100):
            with self.subTest(dense=dense):
                c=self.controller(dense_gap_ms=dense)
                c.tracks=[self.track(c,i,2,1+i*.03) for i in range(4)]
                edges,events=self.simulate(c,end=1.12)
                heads=[e for e in events if 'arrival' in e]
                self.assertEqual(len(heads),4)
                for e in heads:self.assertLessEqual(abs(e['time']-e['target']),.0011)
                lane_edges=[e for e in edges if e[1]=='f' and e[0]>=1.]
                for first,second in zip(lane_edges,lane_edges[1:]):
                    self.assertGreaterEqual(second[0]-first[0]+1e-9,.012 if first[2] else .008)

    def test_short_release_lead_is_extended_without_late_down(self):
        c=self.controller(release_lead_ms=5);c.tracks=[self.track(c,1,2,1.)]
        edges,events=self.simulate(c)
        up=next(t for t,k,down in edges if k=='f' and not down)
        down=next(e['time'] for e in events if 'arrival' in e)
        self.assertAlmostEqual(up,.992);self.assertAlmostEqual(down,1.)

    def test_dense_other_key_does_not_reset_shared_wait(self):
        c=self.controller(dense_gap_ms=100,dense_tap_ms=25)
        c.tracks=[self.track(c,1,1,1.),self.track(c,2,4,1.015)]
        _,events=self.simulate(c)
        heads=[e for e in events if 'arrival' in e]
        self.assertEqual([(e['key'],e['time']) for e in heads],[('d',1.),('k',1.015)])

    def test_alternating_positions_use_exclusive_keys(self):
        c=self.controller()
        c.tracks=[self.track(c,i,lane,1+i*.03,True) for i,lane in enumerate((1,2,1,2))]
        _,events=self.simulate(c)
        heads=[e for e in events if 'arrival' in e]
        self.assertEqual(len(heads),4)
        for event,next_track in zip(heads,c.tracks[1:]):
            self.assertIn(event['input_lane'],c.trigger_lanes(c.tracks[event['id']]))
            self.assertNotIn(event['input_lane'],c.trigger_lanes(next_track))

    def test_pending_lane_is_frozen_after_release(self):
        c=self.controller();first=self.track(c,1,1,1.,True);c.tracks=[first]
        c.poll(.95);self.assertEqual(first['input_lane'],1)
        c.tracks.append(self.track(c,2,2,1.03,True))
        c.poll(.96);self.assertEqual(first['input_lane'],1)
        heads=c.poll(1.)['events'];self.assertEqual(heads[0]['key'],'d')

    def test_same_time_chord_is_not_avoided_as_future_note(self):
        c=self.controller();c.tracks=[self.track(c,1,1,1.,True),self.track(c,2,2,1.,True)]
        self.assertEqual(c.select_input_lane(c.tracks[0],1.,.9),1)

    def test_no_safe_key_records_conflict_and_never_uses_outside_key(self):
        c=self.controller();c.tracks=[self.track(c,i,2,1+i*.03,True) for i in range(2)]
        first=c.tracks[0];lane=c.select_input_lane(first,1.,.9)
        self.assertIn(lane,c.trigger_lanes(first));self.assertGreater(first['input_conflicts'],0)

    def test_late_confirmation_keeps_real_release_gap(self):
        c=self.controller();c.tracks=[self.track(c,1,2,1.)]
        self.assertNotIn('f',c.poll(.999)['keys'])
        self.assertNotIn('f',c.poll(1.001)['keys'])
        self.assertIn('f',c.poll(1.008)['keys'])

    def test_lookahead_zero_keeps_visual_lane(self):
        c=self.controller(key_lookahead_ms=0)
        c.tracks=[self.track(c,1,1,1.,True),self.track(c,2,2,1.03,True)]
        self.assertEqual(c.select_input_lane(c.tracks[0],1.,.9),1)
    def test_recorded_rightmost_three_cells_never_choose_j(self):
        # Actual last observation of #520 in 20261019-223939-468253,
        # frame 3733: outline spills 0.124 chart cells into J's footprint.
        c=self.controller()
        first=self.track(c,520,5,1.)
        first.update(x=.6890625,y=.48518518518518516,
            normalized_width=.13645833333333332/(m.field_edges(c.c,.48518518518518516)[1]-m.field_edges(c.c,.48518518518518516)[0]))
        following=self.track(c,521,5,1.08)
        following.update(x=.6677083333333333,y=.42314814814814816,
            normalized_width=.12083333333333333/(m.field_edges(c.c,.42314814814814816)[1]-m.field_edges(c.c,.42314814814814816)[0]))
        c.tracks=[first,following]
        self.assertEqual(c.trigger_lanes(first),{4,5})
        self.assertIn(c.select_input_lane(first,1.,.9),{4,5})
        _,events=self.simulate(c)
        event=next(e for e in events if e.get('id')==520 and 'arrival' in e)
        self.assertIn(event['key'],{'k','l'})
    def test_exact_outer_three_cells_exclude_boundary_touching_key(self):
        c=self.controller()
        for lane,x0,x1,expected in ((5,9.,12.,{4,5}),(0,0.,3.,{0,1})):
            track=self.track(c,1,lane,1.)
            left,right=m.field_edges(c.c,.4)
            track.update(y=.4,x=left+(x0+x1)/24*(right-left),normalized_width=(x1-x0)/12)
            self.assertEqual(c.trigger_lanes(track),expected)
    def test_small_j_before_coloured_slide_stays_j_in_both_schedulers(self):
        for colour in ('green','yellow'):
            for kind in ('hold','tap'):
                for dense in (0,100):
                    with self.subTest(colour=colour,kind=kind,dense=dense):
                        c=self.controller(dense_gap_ms=dense)
                        first=self.track(c,1,3,1.,True)
                        following=self.track(c,2,2,1.03,True)
                        following.update(color=colour,kind=kind)
                        c.tracks=[first,following]
                        self.assertEqual(c.select_input_lane(first,1.,.9),3)
                        self.assertEqual(first['input_reason'],'centre_before_coloured_slide')
                        _,events=self.simulate(c)
                        pressed=next(e for e in events if e.get('id')==1 and 'arrival' in e)
                        self.assertEqual(pressed['key'],'j')
                        self.assertEqual(pressed['input_reason'],'centre_before_coloured_slide')
    def test_wide_face_and_blue_followers_keep_lookahead(self):
        for wide in (False,True):
            c=self.controller();first=self.track(c,1,3,1.,True);following=self.track(c,2,2,1.03,True)
            if wide:first['normalized_width']=.25;following['color']='green'
            c.tracks=[first,following]
            self.assertEqual(c.select_input_lane(first,1.,.9),4)
    def test_later_colour_overrides_blue_follower_inside_slide_guard(self):
        c=self.controller()
        c.tracks=[self.track(c,1,3,1.,True),self.track(c,2,2,1.03,True),self.track(c,3,2,1.08,True)]
        c.tracks[-1]['color']='green'
        self.assertEqual(c.select_input_lane(c.tracks[0],1.,.9),3)
    def test_independent_slide_guard_boundary_and_disable(self):
        for colour in ('green','yellow'):
            for delay,guard,expected in ((.15,160,3),(.16,160,3),(.161,160,4),(.08,0,4),(.18,200,3)):
                with self.subTest(colour=colour,delay=delay,guard=guard):
                    c=self.controller(slide_guard_ms=guard)
                    first=self.track(c,1,3,1.,True)
                    blue=self.track(c,2,2,1.03,True)
                    slide=self.track(c,3,2,1.+delay,True);slide.update(color=colour,kind='hold')
                    c.tracks=[first,blue,slide]
                    self.assertEqual(c.select_input_lane(first,1.,.9),expected)
    def test_ignored_slide_end_is_not_a_coloured_follower(self):
        c=self.controller();first=self.track(c,1,3,1.,True);following=self.track(c,2,2,1.03,True)
        following.update(color='green',kind='slide_end',fired=True,ignored_reason='slide_end')
        c.tracks=[first,following]
        c.select_input_lane(first,1.,.9)
        self.assertEqual(first['input_reason'],'visual_centre')


if __name__=='__main__':unittest.main()
