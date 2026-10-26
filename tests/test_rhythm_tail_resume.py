import math,unittest
from collections import deque
from test_rhythm_grid import m, ROOT

class TailResumeTests(unittest.TestCase):
    def controller(self,**kw):
        return m.RhythmController(dict(m.load_config(ROOT),input_mode='all-held',release_scope='target',
            input_offset_ms=0,dense_gap_ms=0,**kw))
    def face(self,y,a=3.1,b=5.8,lane=2,kind='tap'):
        left,right=m.field_edges(m.load_config(ROOT),y)
        return m.Note(lane,kind,(left+(a+b)/24*(right-left),y),(b-a)/12*(right-left),.006,1.,'green')
    def test_990_991_split_rejoins_known_parent_and_stays_ignored(self):
        c=self.controller()
        for i,y in enumerate((.0676,.0722,.0778)):c.decide([self.face(y)],i*.015)
        result=c.decide([self.face(.0824,4.59,5.8),self.face(.0824,3.07,4.28,lane=1)],.045)
        self.assertEqual(len(c.tracks),1)
        self.assertTrue(any(e.get('type')=='face_fragments_rejoined' for e in result['events']))
        for i,y in enumerate((.094,.100,.108)):
            c.decide([self.face(y,kind='slide_end')],.06+i*.015)
        self.assertEqual(c.tracks[0].get('ignored_reason'),'slide_end')
        self.assertFalse(any('arrival' in e for e in c.poll(.8)['events']))
    def test_two_real_heads_without_prior_whole_are_not_joined(self):
        c=self.controller()
        for i,y in enumerate((.0676,.0722,.0778,.0824)):
            result=c.decide([self.face(y,4.59,5.8),self.face(y,3.07,4.28,lane=1)],i*.015)
            self.assertFalse(any(e.get('type')=='face_fragments_rejoined' for e in result['events']))
        self.assertEqual(len(c.tracks),2)
    def test_stale_whole_template_cannot_join_later_notes(self):
        c=self.controller()
        for i,y in enumerate((.0676,.0722,.0778)):c.decide([self.face(y)],i*.015)
        result=c.decide([self.face(.0824,4.59,5.8),self.face(.0824,3.07,4.28,lane=1)],.12)
        self.assertFalse(any(e.get('type')=='face_fragments_rejoined' for e in result['events']))
    def test_paused_locked_track_can_fit_then_resume_without_none_subtraction(self):
        c=self.controller(global_flow='active',motion_curve=dict(power=1,offset=0),hit_line_y=.8)
        c.flow.rate=0.;c.flow.base=1.
        c.tracks=[dict(id=1,lane=2,color='blue',kind='tap',fired=False,locked=True,
            arrival=None,lock_until=1.,last=.03,y=.27,x=.45,phase_rate=0.,velocity=0.,stable_fit_count=3,
            history=deque([(0.,.25),(.015,.26),(.03,.27)],maxlen=8))]
        c.sequence=1
        d=c.decide([m.Note(2,'tap',(.45,.28),.08,.02,1.,'blue')],.045)
        self.assertIsNone(c.tracks[0]['arrival'])
        self.assertFalse(any('arrival' in e for e in d['events']))
        c.flow.rate=1.
        c.decide([m.Note(2,'tap',(.45,.29),.08,.02,1.,'blue')],.06)
        self.assertTrue(math.isfinite(c.tracks[0]['arrival']))

if __name__=='__main__':unittest.main()
