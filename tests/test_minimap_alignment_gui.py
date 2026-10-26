"""Exercise the editor's own event handlers in a hidden Tk window, no desktop input."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from modular_agent.domains.hololive_dreams.patrol_vision import write_image


class EditorTests(unittest.TestCase):
    def test_pair_undo_drag_and_save_handlers(self):
        import tkinter as tk
        try:
            root = tk.Tk();root.withdraw()
        except tk.TclError as error:
            self.skipTest(str(error))
        spec = importlib.util.spec_from_file_location('minimap_alignment_gui_test',Path(__file__).resolve().parents[1]/'tools/minimap_align.py')
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        try:
            with tempfile.TemporaryDirectory() as folder:
                folder = Path(folder);source = folder/'source';(source/'tiles').mkdir(parents=True)
                rows = []
                for i in range(7):
                    write_image(source/'tiles'/f'{i+1:06d}.png',np.full((164,164,3),120,np.uint8))
                    rows.append(dict(frame_id=i+1,t=i*.25,x=i*10,y=0,accepted=True))
                (source/'frames.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
                with patch.object(module.messagebox,'showerror',side_effect=AssertionError('GUI handler error')):
                    app = module.AlignmentEditor(root,source,project_file=folder/'project.json')
                    app.current = 7;app.reference = 1;app.sync()
                    app.pending = {'a':[120,40],'b':[72,40]};app.add_pair()
                    self.assertLess(app.project.residuals[0],.03)
                    app.undo()
                    self.assertEqual(len(app.project.data['pairs']),0)
                    app.click(SimpleNamespace(x=20,y=20),'overlay')
                    before = app.project.pose(7)
                    scale = app.overlay_scale
                    app.drag_overlay(SimpleNamespace(x=30,y=20))
                    app.end_drag(SimpleNamespace(x=30,y=20))
                    self.assertAlmostEqual(app.project.pose(7)[0]-before[0],10/scale,delta=.05)
                    app.save()
                    data = json.loads((folder/'project.json').read_text(encoding='utf-8'))
                    self.assertIn('7',data['anchors'])
                    self.assertEqual(data['view']['current'],7)
                    app.edit_mode.set('画笔擦除');app.mask_scope.set('仅当前帧')
                    scale,offset = app.raw_transforms['b']
                    point = offset+np.array((120,60))*scale
                    app.click(SimpleNamespace(x=point[0],y=point[1]),'b')
                    end = offset+np.array((124,60))*scale
                    app.left_motion(SimpleNamespace(x=end[0],y=end[1]),'b')
                    self.assertEqual(app.visible_mask(7)[60,120],0)
                    app.end_drag(SimpleNamespace(x=end[0],y=end[1]))
                    self.assertEqual(app.project.mask(7)[60,120],0)
                    self.assertTrue(app.project.mask(1)[60,120])
                    app.undo();self.assertTrue(app.project.mask(7)[60,120])
                    app.edit_mode.set('多边形擦除');app.mask_scope.set('全部帧通用')
                    for pixel in ((112,40),(136,64),(112,80)):
                        scale,offset = app.raw_transforms['b'];point = offset+np.array(pixel)*scale
                        app.click(SimpleNamespace(x=point[0],y=point[1]),'b')
                    app.finish_polygon()
                    self.assertEqual(app.project.mask(1)[60,120],0)
                    self.assertEqual(app.project.mask(7)[60,120],0)
                    app.outer_size.set('74');app.center_size.set('26');app.apply_circle()
                    self.assertTrue(app.project.mask(1)[82,12])
                    app.load(source,source/'frames.jsonl',folder/'manual-project.json',from_zero=True)
                    self.assertEqual(app.project.selected_ids(),[])
                    self.assertIsNone(app.overview_image)
                    app.confirm_current()
                    self.assertEqual(app.project.selected_ids(),[1])
                    app.current = 7;app.sync();app.nudge(1,0)
                    self.assertEqual(app.project.selected_ids(),[1])
                    app.confirm_current()
                    self.assertEqual(app.project.selected_ids(),[1,7])
                    app.render_overview();self.assertIsNotNone(app.overview_image)
                    scale = app.overview_scale;origin = app.overview_origin.copy()
                    world = app.project.pose(7)+np.array((120,60))-82
                    screen = (world-origin)*scale
                    other_before = app.project.pose(1)
                    app.overview_press(SimpleNamespace(x=screen[0],y=screen[1]))
                    self.assertIsNotNone(app.overview_drag)
                    moving_before = app.project.pose(app.current)
                    app.overview_motion(SimpleNamespace(x=screen[0]+10,y=screen[1]))
                    app.overview_release(SimpleNamespace(x=screen[0]+10,y=screen[1]))
                    self.assertAlmostEqual(app.project.pose(7)[0]-moving_before[0],10/scale,delta=.05)
                    np.testing.assert_array_equal(app.project.pose(1),other_before)
        finally:
            root.destroy()


if __name__=='__main__':
    unittest.main()
