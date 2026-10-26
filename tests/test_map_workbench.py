import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.realtime.map_workbench import MapWorkspace,MapWorkbench,valid_reference
from modular_agent.domains.hololive_dreams.patrol_vision import write_image


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_image(self.root/'map.png',np.full((100,120,3),150,np.uint8))
        write_image(self.root/'coverage.png',np.full((100,120),255,np.uint8))
        (self.root/'config.json').write_text(json.dumps(dict(reference='map.png',coverage='coverage.png',minimap={})))

    def create(self,name='新地图',reference=None):return MapWorkspace.create(name,root=self.root/'projects',reference=reference)

    def test_maps_recordings_and_references_are_isolated(self):
        a,b = self.create('图一'),self.create('图二')
        self.assertNotEqual(a.root,b.root)
        output = a.new_recording('repair');output.mkdir(parents=True)
        write_image(output/'map.png',np.full((100,120,3),150,np.uint8))
        (output/'patrol-config.json').write_text(json.dumps(dict(reference='map.png')))
        self.assertEqual(a.reference(),output/'patrol-config.json')
        self.assertIsNone(b.reference());self.assertIsNone(b.manual_reference())

    def test_capture_arguments_are_passive_and_use_project_config(self):
        project = self.create();output = project.new_recording('scan')
        args = project.capture_args(output)
        self.assertIn('--clean-overlays',args);self.assertNotIn('--auto-walk',args)
        self.assertEqual(args[args.index('--config')+1],str(project.root/'capture-config.json'))
        self.assertEqual(args[args.index('--stop-file')+1],str(output/'STOP'))

    def test_repair_requires_this_maps_manual_export(self):
        project = self.create()
        with self.assertRaisesRegex(ValueError,'手工'):project.capture_args(project.root/'output',repair=True)
        folder = project.root/'alignment'/'session'/'exports'/'one';folder.mkdir(parents=True)
        (folder/'alignment.json').write_text('{}');write_image(folder/'map.png',np.zeros((100,120,3),np.uint8))
        (folder/'patrol-config.json').write_text(json.dumps(dict(reference='map.png')))
        args = project.capture_args(project.root/'output',repair=True)
        self.assertEqual(args[args.index('--reference-config')+1],str(folder/'patrol-config.json'))

    def test_annotation_projects_do_not_share_even_when_map_images_match(self):
        a,b = self.create('A',self.root/'config.json'),self.create('B',self.root/'config.json')
        first,second = a.annotation(),b.annotation()
        self.assertNotEqual(first.path,second.path)
        first.add_point([10,20]);first.save()
        self.assertEqual(len(a.annotation().data['points']),1)
        self.assertEqual(b.annotation().data['points'],[])

    def test_missing_resume_state_and_invalid_reference_are_rejected(self):
        project = self.create()
        with self.assertRaises(ValueError):project.capture_args(project.root/'output',resume=self.root)
        self.assertFalse(valid_reference(self.root/'missing.json'))
        with self.assertRaises(ValueError):project.capture_args(project.root/'output',duration=9000)

    def test_hidden_workbench_launches_only_selected_map_and_does_not_capture(self):
        a,b = self.create('A'),self.create('B')
        app = MapWorkbench(root=self.root/'projects',visible=False)
        try:
            app.workspace = b;app.update_info()
            with patch.object(app,'launch') as launch:
                app.capture()
                args = launch.call_args.args[0]
                self.assertIn(str(b.root/'capture-config.json'),args)
                self.assertNotIn(str(a.root/'capture-config.json'),args)
        finally:app.root.destroy()


if __name__=='__main__':unittest.main()
