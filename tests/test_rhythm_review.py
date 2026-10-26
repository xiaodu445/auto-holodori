import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
import cv2,numpy as np
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('review_tests_module',ROOT/'tools/rhythm_review.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)

class RhythmReviewTests(unittest.TestCase):
    def video(self,folder):
        path=folder/'sample.avi';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),60,(720,404))
        self.assertTrue(writer.isOpened())
        for i in range(36):
            image=np.zeros((404,720,3),np.uint8);cy=int((.4+i*.012)*404)
            cv2.rectangle(image,(325,cy-10),(400,cy+10),(245,200,70),-1);writer.write(image)
        writer.release();return path
    def test_complete_export_no_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);video=self.video(folder);out=folder/'review'
            # Offline analysis must never create the live input executor.
            with patch('modular_agent.computer.ActionComputer',side_effect=AssertionError('input forbidden')):
                data=m.analyze(video,out,duration=2)
            self.assertEqual(len(data['frames']),36)
            self.assertEqual(len(list((out/'frames').glob('*.jpg'))),36)
            self.assertTrue(all(e['simulated'] for e in data['input_edges']))
            self.assertTrue(data['input_edges'])
            html=(out/'index.html').read_text(encoding='utf-8')
            self.assertNotIn('/*REVIEW_DATA*/',html)
            self.assertIn(data['sha256'],html)
            self.assertTrue(any(f['events'] for f in data['frames']))
    def test_recorded_timestamps_and_manual_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);video=self.video(folder);stamp=folder/'timestamps.json'
            stamp.write_text(json.dumps([dict(t=5+i*.02) for i in range(36)]),encoding='utf-8')
            (folder/'inputs.json').write_text(json.dumps([dict(t=5.2,key='f',down=True),dict(t=5.25,key='f',down=False)]),encoding='utf-8')
            data=m.analyze(video,folder/'out',timestamps=stamp,duration=2)
            self.assertAlmostEqual(data['frames'][-1]['time'],.7)
            self.assertAlmostEqual(data['recorded_input_edges'][0]['time'],.2)
            self.assertFalse(data['recorded_input_edges'][0]['simulated'])
    def test_invalid_timestamp_order_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);video=self.video(folder);stamp=folder/'timestamps.json'
            stamp.write_text('[{"t":2},{"t":1}]',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'nonmonotonic'):m.analyze(video,folder/'out',timestamps=stamp)
    def test_full_song_uses_timestamp_end_not_twenty_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);video=self.video(folder);stamp=folder/'timestamps.json'
            # Sparse synthetic timestamps test range/segmentation, not FPS.
            stamp.write_text(json.dumps([dict(t=5+i*.9) for i in range(36)]),encoding='utf-8')
            with patch('modular_agent.computer.ActionComputer',side_effect=AssertionError('input forbidden')):
                data=m.analyze(video,folder/'full',timestamps=stamp,duration=None,segment_seconds=30)
            self.assertEqual(len(data['frames']),36)
            self.assertAlmostEqual(data['frames'][-1]['time'],31.5)
            self.assertEqual(data['reason'],'video_end')
            overview=(folder/'full/index.html').read_text(encoding='utf-8')
            self.assertIn('part-0001.html',overview);self.assertIn('part-0002.html',overview)
            part=(folder/'full/part-0002.html').read_text(encoding='utf-8')
            self.assertIn('全曲总览',part)
            self.assertIn('frames/000035.jpg',part)
            self.assertNotIn('frames/000000.jpg',part)
    def test_page_boundary_preserves_hold_without_fake_press(self):
        edges=[dict(time=1,key='f',down=True,simulated=False),dict(time=5,key='f',down=False,simulated=False)]
        clipped=m.clip_edges(edges,2,4)
        self.assertEqual([(e['time'],e['down']) for e in clipped],[(2,True),(4,False)])
        self.assertTrue(all(e['segment_boundary'] for e in clipped))
        self.assertTrue(all(not e['simulated'] for e in clipped))
        self.assertEqual(edges[0]['time'],1)

if __name__=='__main__':unittest.main()
