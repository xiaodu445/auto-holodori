import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from modular_agent.realtime.kitchen_labels import LabelStore


class LabelTests(unittest.TestCase):
    def prepare(self,path):
        (path/'timestamps.json').write_text(json.dumps([dict(t=.1),dict(t=.2)]))
        writer=cv2.VideoWriter(str(path/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(48,32))
        self.assertTrue(writer.isOpened())
        for i in range(2):writer.write(np.zeros((32,48,3),np.uint8))
        writer.release()
        return LabelStore(path)

    def test_save_reload_preserves_instances_and_ignore(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);store=self.prepare(path);frame=store.frame(0,48,32)
            a=store.add_point(frame,'chili',12,16);b=store.add_point(frame,'chili',20,16)
            self.assertNotEqual(a['instance_id'],b['instance_id'])
            store.add_ignore(frame,[25,10,35,20]);store.save()
            restored=LabelStore(path).frame(0,48,32)
            self.assertEqual(restored,frame)
            self.assertFalse(restored['complete'])

    def test_export_only_complete_and_modification_invalidates(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);store=self.prepare(path);frame=store.frame(0,48,32)
            store.add_point(frame,'chili',12,16);frame['complete']=True
            store.frame(1,48,32)
            output,count=store.export(dict(chili=dict(name='辣椒')))
            self.assertEqual(count,1)
            manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['frames'][0]['points'][0]['x'],12)
            self.assertEqual(cv2.imread(str(output/'frame-000000.png')).shape,(32,48,3))
            store.add_ignore(frame,[25,10,35,20]);self.assertFalse(frame['complete'])
            _,count=store.export(dict(chili=dict(name='辣椒')))
            self.assertEqual(count,0)

    def test_mismatched_recording_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);store=self.prepare(path);store.save()
            (path/'timestamps.json').write_text('[{"t":9}]')
            with self.assertRaises(ValueError):LabelStore(path)

    def test_invalid_coordinates_and_unknown_class(self):
        with tempfile.TemporaryDirectory() as folder:
            store=self.prepare(Path(folder));frame=store.frame(0,48,32)
            with self.assertRaises(ValueError):store.add_point(frame,'chili',49,2)
            with self.assertRaises(ValueError):store.add_ignore(frame,[20,10,10,20])
            store.add_point(frame,'unknown',10,10);frame['complete']=True
            with self.assertRaises(ValueError):store.export({})


class ConcurrentLabelTests(LabelTests):
    def test_two_stores_preserve_different_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);first=self.prepare(path);first.save();second=LabelStore(path)
            first.add_point(first.frame(0,48,32),'chili',12,16);first.save()
            second.add_point(second.frame(1,48,32),'rice',20,16);second.save()
            restored=LabelStore(path)
            self.assertEqual(len(restored.data['frames']['0']['points']),1)
            self.assertEqual(len(restored.data['frames']['1']['points']),1)

    def test_same_frame_conflict_retains_local_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);first=self.prepare(path);first.frame(0,48,32);first.save();second=LabelStore(path)
            first.add_point(first.frame(0,48,32),'chili',12,16);first.save()
            second.add_point(second.frame(0,48,32),'rice',20,16)
            with self.assertRaises(RuntimeError):second.save()
            self.assertEqual(len(list((path/'point-labels').glob('conflict-*.json'))),1)
            self.assertEqual(LabelStore(path).data['frames']['0']['points'][0]['class_id'],'chili')


class LabelGuiTests(unittest.TestCase):
    def test_gui_point_ignore_undo_and_reload(self):
        import importlib.util
        import tkinter as tk
        from types import SimpleNamespace
        from unittest.mock import patch
        module_path=Path(__file__).resolve().parents[1]/'tools/kitchen_point_label.py'
        spec=importlib.util.spec_from_file_location('label_gui',module_path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'timestamps.json').write_text('[{"t":35},{"t":36}]')
            writer=cv2.VideoWriter(str(path/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(480,320))
            for i in range(2):writer.write(np.zeros((320,480,3),np.uint8))
            writer.release()
            catalog=path/'classes.json'
            catalog.write_text('{"classes":[{"id":"chili","name":"chili"}]}')
            root=tk.Tk();root.withdraw()
            try:
                app=module.Annotator(root,path,catalog)
                event=SimpleNamespace(x=int(200*app.scale),y=int(150*app.scale))
                app.press(event)
                self.assertEqual(len(app.frame['points']),1)
                app.listbox.selection_set(0);app.highlight_selection()
                self.assertEqual(app.canvas.itemcget('label:0','fill'),'#ff3b30')
                self.assertEqual(app.canvas.itemcget('point:0','outline'),'#ff3b30')
                app.listbox.selection_clear(0,'end');app.highlight_selection()
                self.assertEqual(app.canvas.itemcget('label:0','fill'),'#00ff00')
                app.complete.set(True);app.mark_complete()
                self.assertTrue(app.frame['complete'])
                app.mode.set('ignore');app.press(event)
                app.release(SimpleNamespace(x=int(240*app.scale),y=int(190*app.scale)))
                self.assertEqual(len(app.frame['ignore_regions']),1)
                self.assertTrue(app.frame['complete'])  # User policy: any human-labelled frame is complete.
                app.undo();self.assertEqual(len(app.frame['ignore_regions']),0)
                self.assertTrue(app.frame['complete'])
                app.navigate(1);app.navigate(0)
                self.assertEqual(len(app.frame['points']),1)
                app.close()
                restored=LabelStore(path)
                self.assertTrue(restored.data['frames']['0']['complete'])
            finally:
                try:root.destroy()
                except tk.TclError:pass


class LabeledNavigationTests(unittest.TestCase):
    def test_startup_prefers_complete_frame_and_navigation(self):
        import importlib.util
        import tkinter as tk
        spec=importlib.util.spec_from_file_location('label_gui_navigation',Path(__file__).resolve().parents[1]/'tools/kitchen_point_label.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);store=LabelTests().prepare(path)
            store.add_point(store.frame(0,48,32),'chili',20,16)
            store.frame(1,48,32)['complete']=True;store.save()
            catalog=path/'classes.json';catalog.write_text('{"classes":[{"id":"chili","name":"chili"}]}')
            root=tk.Tk();root.withdraw()
            try:
                app=module.Annotator(root,path,catalog)
                self.assertEqual(app.index,1)
                self.assertEqual(app.review_indices,[0,1])
                app.labeled_step(-1);self.assertEqual(app.index,0)
                app.labeled_step(1);self.assertEqual(app.index,1)
                app.close()
            finally:
                try:root.destroy()
                except tk.TclError:pass


class ManualQueueTests(unittest.TestCase):
    def test_isolated_workspace_and_queue_navigation(self):
        import importlib.util
        import tkinter as tk
        spec=importlib.util.spec_from_file_location('queue_gui',Path(__file__).resolve().parents[1]/'tools/kitchen_point_label.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);reference=LabelTests().prepare(path)
            reference.add_point(reference.frame(0,48,32),'chili',20,16);reference.save()
            before=reference.path.read_bytes()
            workspace=path/'manual';workspace.mkdir()
            (workspace/'selection.json').write_text(json.dumps(dict(frames=[dict(video_index=1,t=.2,reason='first'),dict(video_index=0,t=.1,reason='second')])))
            catalog=path/'classes.json';catalog.write_text('{"classes":[{"id":"chili","name":"chili"}]}')
            root=tk.Tk();root.withdraw()
            try:
                app=module.Annotator(root,path,catalog,workspace)
                self.assertEqual(app.index,1)
                self.assertEqual(app.frame['points'],[])
                app.queue_step(1);self.assertEqual(app.index,0)
                self.assertEqual(app.frame['points'],[])
                app.store.add_point(app.frame,'chili',20,16);app.changed()
                app.queue_step(-1);self.assertEqual(app.index,1)
                app.close()
                self.assertEqual(reference.path.read_bytes(),before)
                self.assertEqual(len(LabelStore(path,workspace).data['frames']['0']['points']),1)
            finally:
                try:root.destroy()
                except tk.TclError:pass


class ClassAliasTests(unittest.TestCase):
    def test_alias_load_save_and_new_point_preserve_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);original=LabelTests().prepare(path)
            original.add_point(original.frame(0,48,32),'egg_brown',20,16);original.save()
            (original.labels_dir/'class-aliases.json').write_text('{"egg_brown":"Yellow_egg"}')
            merged=LabelStore(path)
            point=merged.data['frames']['0']['points'][0]
            self.assertEqual((point['class_id'],point['x'],point['y']),('Yellow_egg',20,16))
            new=merged.add_point(merged.frame(0,48,32),'egg_brown',25,20)
            self.assertEqual(new['class_id'],'Yellow_egg')
            merged.save()
            saved=json.loads(merged.path.read_text(encoding='utf-8'))
            self.assertTrue(all(p['class_id']=='Yellow_egg' for p in saved['frames']['0']['points']))


class BboxTests(unittest.TestCase):
    def test_bbox_requires_existing_point_inside_and_preserves_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            store=LabelTests().prepare(Path(folder));frame=store.frame(0,48,32)
            point=store.add_point(frame,'chili',20,16);frame['complete']=True
            with self.assertRaises(ValueError):store.set_bbox(frame,point['instance_id'],[0,0,10,10])
            with self.assertRaises(ValueError):store.set_bbox(frame,point['instance_id'],[-1,0,25,25])
            store.set_bbox(frame,point['instance_id'],[12,10,29,25]);store.save()
            self.assertTrue(frame['complete']);self.assertEqual((point['x'],point['y']),(20,16))
            self.assertEqual(LabelStore(Path(folder)).data['frames']['0']['points'][0]['bbox'],[12,10,29,25])


class UserSelectionTests(unittest.TestCase):
    def test_pick_frames_is_idempotent_and_does_not_auto_label(self):
        import importlib.util
        import tkinter as tk
        spec=importlib.util.spec_from_file_location('selection_gui',Path(__file__).resolve().parents[1]/'tools/kitchen_point_label.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);LabelTests().prepare(path)
            work=path/'new_manual';catalog=path/'classes.json'
            catalog.write_text('{"classes":[{"id":"chili","name":"chili"}]}')
            root=tk.Tk();root.withdraw()
            try:
                app=module.Annotator(root,path,catalog,work,selection_mode=True)
                app.navigate(0);app.select_current();app.select_current()
                self.assertEqual(app.queue_indices,[0])
                app.navigate(1);app.select_current();self.assertEqual(app.queue_indices,[0,1])
                app.unselect_current();self.assertEqual(app.queue_indices,[0])
                self.assertFalse(any(f['points'] for f in app.store.data['frames'].values()))
                app.close()
                selection=json.loads((work/'selection.json').read_text(encoding='utf-8'))
                self.assertEqual(selection['selected_by'],'user')
                self.assertEqual([f['video_index'] for f in selection['frames']],[0])
            finally:
                try:root.destroy()
                except tk.TclError:pass


class EditorEnhancementTests(unittest.TestCase):
    def test_zoom_scroll_coordinates_rank_and_frame_save(self):
        import importlib.util
        import tkinter as tk
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('enhanced_gui',Path(__file__).resolve().parents[1]/'tools/kitchen_point_label.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);LabelTests().prepare(path)
            catalog=path/'classes.json';catalog.write_text('{"classes":[{"id":"chili","name":"chili"},{"id":"onion","name":"onion"}]}')
            root=tk.Tk();root.withdraw()
            try:
                app=module.Annotator(root,path,catalog,path/'manual',selection_mode=True)
                app.set_zoom(2)
                app.canvas.configure(width=200,height=100);root.update_idletasks()
                app.canvas.xview_moveto(.2);app.canvas.yview_moveto(.1)
                event=SimpleNamespace(x=70,y=60)
                x,y=app.point(event)
                self.assertEqual(x,int(app.canvas.canvasx(70)/app.scale))
                self.assertEqual(y,int(app.canvas.canvasy(60)/app.scale))
                app.apply_prediction({'onion':.9,'chili':.2,'unknown':1})
                self.assertTrue(app.options[0].endswith(' | onion'))
                self.assertEqual(app.class_id(),'chili')
                self.assertFalse(app.frame['points'])
                app.persist_frame()
                self.assertTrue((path/'manual/frames'/f'frame-{app.index:06d}.png').exists())
                self.assertEqual(cv2.imread(str(path/'manual/frames'/f'frame-{app.index:06d}.png')).shape,app.image.shape)
                from unittest.mock import patch
                with patch.object(module.filedialog,'askopenfilename',return_value=str(path/'screen.avi')),patch.object(module.Annotator,'__init__',return_value=None) as reopen:
                    app.open_recording()
                    self.assertTrue(reopen.called)
                    self.assertEqual(reopen.call_args.args[1],path)
                    self.assertEqual(reopen.call_args.args[3].name,path.name)
                app.cap.release()
            finally:
                try:root.destroy()
                except tk.TclError:pass
