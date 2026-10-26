import importlib.util,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('offset_test_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class OffsetTests(unittest.TestCase):
    def test_production_offset_and_head_deadline(self):
        config=m.load_config(ROOT);self.assertEqual(config['input_offset_ms'],10)
        config['input_offset_ms']=10  # Explicit opt-in compensation still works.
        c=m.RhythmController(config)
        c.tracks=[dict(id=1,lane=2,color='blue',kind='tap',locked=True,lock_until=1.035,arrival=1.,last=.8,fired=False,prediction_source='middle_zone')]
        self.assertEqual(c.poll(.989)['events'],[])
        event=c.poll(.990)['events'][0]
        self.assertEqual(event['arrival'],1.)
        self.assertAlmostEqual(event['target'],.990)
    def test_offset_shifts_route_not_visual_estimate(self):
        results=[]
        for offset in (0,10):
            config=dict(m.load_config(ROOT),input_offset_ms=offset,motion_curve={'power':1.,'offset':0.})
            c=m.RhythmController(config)
            for i in range(30,60):
                now=i*.01;y=config['hit_line_y']+(now-1.)*.8
                c.decide([m.Note(2,'hold',(.45,y),.08,.02,1.,'green',((.45,y-.05,.08),(.53,y-.10,.08)))],now)
            track=next(t for t in c.tracks if t.get('locked'))
            results.append((track['arrival'],track['hold_route']))
        self.assertAlmostEqual(results[0][0],results[1][0])
        for a,b in zip(results[0][1],results[1][1]):
            self.assertEqual(a[1],b[1]);self.assertAlmostEqual(a[0]-b[0],.010)

if __name__=='__main__':unittest.main()
