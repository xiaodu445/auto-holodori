import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import cv2
from modular_agent.realtime.trajectory_bank import TrajectoryBank,AngularWarp
from modular_agent.realtime.export_jump_rope_review import export
ROOT=Path(__file__).resolve().parents[1]
def config():return json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear_config.json').read_text())

class ReviewTests(unittest.TestCase):
    def test_reverse_half_uses_own_entry_boundary(self):
        c=config();c['swing_boundary_by_branch']=True;b=TrajectoryBank(c,.65,.4)
        p=b.make('low_swing',.7,0,-1);b.items=[p];b.active=p.key;b.time=0;b.low_entry_direction=-1;b.low_played_cycles=1.1
        self.assertAlmostEqual(b.swing_boundary(p),.7)
        p.phase=1.39;b.advance(.05)
        self.assertFalse(any(x.mode!='low_swing' for x in b.items))
        p.phase=1.69;b.advance(.10)
        self.assertTrue(any(x.mode=='rotation_forward' for x in b.items))
    def test_late_confirmation_keeps_elapsed_low_clock(self):
        c=config();c['swing_boundary_by_branch']=True;b=TrajectoryBank(c,.65,.4);b.acquire(.65,0)
        old=next(x for x in b.items if x.key==b.active);p=b.make('low_swing',.7,0,-1,parent=old.key);p.phase=.87;b.items.append(p)
        b.commit_episode(old,p);self.assertAlmostEqual(b.low_played_cycles,.17)
    def test_gear_child_keeps_episode_entry(self):
        c=config();c['swing_boundary_by_branch']=True;b=TrajectoryBank(c,.65,.4)
        p=b.make('low_swing',.7,0,-1);b.items=[p];child=b.make('low_swing',1.7,0,-1,parent=p.key)
        self.assertAlmostEqual(child.entry_phase,.7)
    def test_baseline_keeps_fixed_boundary(self):
        b=TrajectoryBank(config(),.65,.4);p=b.make('low_swing',.7,0)
        self.assertEqual(b.swing_boundary(p),b.swing_entry)
    def test_smoothed_missing_endpoint_reduces_peak_angular_speed(self):
        folder=ROOT/'domains/hololive_dreams/data/jump_rope_phase'
        old=AngularWarp(json.loads((folder/'swing_time_v1.json').read_text())['profile']);new=AngularWarp(json.loads((folder/'swing_time_v2.json').read_text())['profile'])
        ts=np.linspace(0,.1,200);self.assertLess(max(new.evaluate(t)[1] for t in ts),max(old.evaluate(t)[1] for t in ts))
        self.assertTrue(all(new.evaluate(t)[1]>0 for t in np.linspace(0,1,1000)))
    def test_export_exact_frame_count_and_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'domains/hololive_dreams/models/jump_rope';folder.mkdir(parents=True)
            (folder/'jump_rope_config.json').write_bytes((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_config.json').read_bytes())
            (root/'settings.json').write_text('{}');(root/'video').mkdir()
            writer=cv2.VideoWriter(str(root/'video/screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),30,(100,100))
            for _ in range(2):writer.write(np.zeros((100,100,3),np.uint8))
            writer.release();(root/'video/timestamps.json').write_text(json.dumps([{'t':.1},{'t':.15}]))
            o=dict(phase_estimate=dict(locked=True,phase=0.,phase_unwrapped=0.,clock_rate=.7,rate=.7,template_acceleration=0.,confidence=.2),motion_state='rotation_forward',tracking_status='coasting',rope_valid=False,whole_curve=[[.3,.4],[.7,.4]],whole_point_states=['unknown','unknown'],phase_visual_quality=0.,whole_coverage=0.,selected_hypothesis=1)
            (root/'replay.json').write_text(json.dumps([dict(time=t,observation=o,decision={}) for t in [.1,.15]]))
            result=export(root,'replay.json','video','review','settings.json');self.assertEqual(result['frames'],2)
            self.assertEqual(len(list((root/'review/frames').glob('*.jpg'))),2)
            rows=[json.loads(line) for line in (root/'review/frames.jsonl').read_text().splitlines()]
            self.assertAlmostEqual(rows[1]['dt'],.05);self.assertIsNone(rows[0]['stage'])
            page=(root/'review/index.html').read_text(encoding='utf-8');self.assertNotIn('/*FRAME_DATA*/',page)
            self.assertIn('jump-rope-human-labels.json',page)
            (root/'video/timestamps.json').write_text('[{"t":0.11},{"t":0.15}]')
            with self.assertRaises(ValueError):export(root,'replay.json','video','other','settings.json')
