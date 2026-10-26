import importlib.util,sys,unittest
from pathlib import Path
from types import SimpleNamespace
import cv2,numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hold_protection_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class HoldProtectionTests(unittest.TestCase):
    def setUp(self):self.config=m.load_config(ROOT)
    def test_all_colours_below_red_are_not_detected_or_used_as_paths(self):
        hsv=np.zeros((540,960,3),np.uint8)
        for index,hue in enumerate((98,60,28,155)):
            cv2.rectangle(hsv,(200+index*140,365),(330+index*140,390),(hue,190,245),-1)
        v=m.RhythmVision(self.config)
        self.assertEqual(v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0),[])
        self.assertEqual(v.hold_paths,[])
    def test_bar_cut_by_roi_does_not_spawn_fragment(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(370,275),(570,310),(98,190,245),-1)
        self.assertEqual(m.RhythmVision(self.config).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0),[])
    def test_red_noise_does_not_change_upper_detection(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(400,145),(520,161),(98,190,245),-1)
        v=m.RhythmVision(self.config);before=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
        hsv[300:]=np.random.default_rng(2).integers(0,255,hsv[300:].shape,dtype=np.uint8)
        after=v.detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),.01)
        self.assertTrue(before);self.assertEqual(before,after);self.assertEqual(v.hold_paths,[])
    def test_coloured_thin_sparkles_are_not_heads(self):
        for hue in (60,28):
            hsv=np.zeros((540,960,3),np.uint8)
            cv2.rectangle(hsv,(200,150),(700,239),(hue,120,180),-1)
            cv2.rectangle(hsv,(400,240),(460,243),(hue,190,245),-1)
            notes=m.RhythmVision(self.config).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0)
            self.assertEqual(notes,[])
    def test_foreign_wide_colour_region_is_not_a_matching_tail(self):
        hsv=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(hsv,(200,170),(700,269),(60,120,180),-1)
        cv2.rectangle(hsv,(370,270),(450,286),(60,190,245),-1)
        notes=[n for n in m.RhythmVision(self.config).detect(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),0) if n.color=='green']
        self.assertTrue(notes);self.assertTrue(all(n.kind=='tap' for n in notes))
    def controller(self,new_lane=1,new_color='blue'):
        c=m.RhythmController(self.config)
        c.holds[10]=dict(lane=1,color='green',start=0.,last=0.,trusted_route=True,route=[],route_index=0)
        c.tracks=[dict(id=20,lane=new_lane,color=new_color,kind='tap',y=.4,x=.4,last=0.,locked=True,lock_until=.135,arrival=.1,fired=False,prediction_source='middle_zone')]
        return c
    def test_same_key_gets_real_release_then_press(self):
        c=self.controller();calls=[]
        class Computer:
            def perform(self,a):
                calls.append((a.name,a.arguments['key']));return SimpleNamespace(outcome=m.Outcome.SUCCESS,message='test')
        keys=m.KeyState(Computer(),True,self.config['keys']);keys.update({'d'})
        d=c.poll(.09);keys.update(d['keys'])
        self.assertNotIn('d',d['keys']);self.assertNotIn(10,c.holds)
        self.assertNotIn('d',c.poll(.095)['keys'])
        d=c.poll(.1);keys.update(d['keys'])
        self.assertEqual(calls,[('key_down','d'),('key_up','d'),('key_down','d')])
        self.assertEqual(len([e for e in d['events'] if 'arrival' in e]),1)
        self.assertEqual(c.poll(.101)['events'],[])
    def test_adjacent_same_colour_note_is_not_swallowed(self):
        c=self.controller(new_lane=2,new_color='green');d=c.poll(.1)
        self.assertIn('d',d['keys']);self.assertIn('f',d['keys'])
        self.assertEqual(len([e for e in d['events'] if 'arrival' in e]),1)
        self.assertIn(10,c.holds)
    def test_bottom_ghost_path_cannot_move_hold(self):
        c=self.controller();c.tracks=[]
        for now in (.05,.1,.3):
            d=c.poll(now,[dict(color='green',lane=0)])
            self.assertEqual(d['keys'],{'d'})
    def test_trusted_route_changes_lane_without_bottom_observations(self):
        c=self.controller();c.tracks=[];c.holds[10]['route']=[(.15,2),(.25,3)]
        self.assertEqual(c.poll(.1)['keys'],{'d'})
        self.assertEqual(c.poll(.16)['keys'],{'f'})
        self.assertEqual(c.poll(.26)['keys'],{'j'})
        self.assertEqual(c.poll(1.)['keys'],{'j'})
        self.assertEqual(c.poll(21.)['keys'],set())
    def test_recorded_route_boundary_jitter_does_not_oscillate(self):
        config=dict(self.config,motion_curve={'power':1.,'offset':0.});c=m.RhythmController(config)
        for i in range(35,66):
            now=i*.01;y=config['hit_line_y']+(now-1.)*.8;tail=[]
            for j,position in enumerate((2.98,3.02,2.99,3.12,3.01,2.98,3.03)):
                py=y-.03-j*.008;l,r=m.field_edges(config,py)
                tail.append((l+(r-l)*position/6,py,.08))
            c.decide([m.Note(2,'hold',(.45,y),.08,.02,1,'green',tuple(tail))],now)
        c.poll(1.001);result=c.poll(1.2)
        turns=[e for e in result['events'] if e.get('type')=='hold_route_step']
        self.assertEqual(len(turns),1);self.assertEqual(result['keys'],{'j'})

if __name__=='__main__':unittest.main()
