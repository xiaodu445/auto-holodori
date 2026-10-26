import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from modular_agent.realtime.minimap_alignment import AlignmentProject,atomic_json,matching_placements,solve_graph
from modular_agent.domains.hololive_dreams.patrol_vision import write_image


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(1)
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        self.source = self.root/'recording';(self.source/'tiles').mkdir(parents=True)
        rng = np.random.default_rng(51)
        world = cv2.resize(rng.integers(20,235,(40,60,3),np.uint8),(480,320),interpolation=cv2.INTER_NEAREST)
        self.rows = []
        for i in range(7):
            image = world[78:242,118+i*8:282+i*8]
            write_image(self.source/'tiles'/f'{i+1:06d}.png',image)
            self.rows.append(dict(frame_id=i+1,t=i*.25,x=i*10.,y=0.,accepted=True))
        (self.source/'frames.jsonl').write_text('\n'.join(json.dumps(row) for row in self.rows),encoding='utf-8')
        self.project_file = self.root/'edit'/'project.json'
        self.project = AlignmentProject(self.source,project_file=self.project_file)

    def tearDown(self):
        self.temp.cleanup()

    def test_unedited_trajectory_exactly_unchanged(self):
        np.testing.assert_array_equal(self.project.corrected,self.project.base)

    def test_one_anchor_smoothly_corrects_entire_interval(self):
        self.project.anchor(7,(48,0))
        self.assertAlmostEqual(self.project.pose(7)[0],48,delta=.03)
        self.assertAlmostEqual(self.project.pose(4)[0],24,delta=.03)
        self.assertAlmostEqual(self.project.pose(1)[0],0,delta=.03)

    def test_landmark_loop_closure_corrects_drift(self):
        self.project.add_pair(1,(120,40),7,(72,40))
        self.assertAlmostEqual(self.project.pose(7)[0],48,delta=.03)
        self.assertLess(self.project.residuals[0],.03)

    def test_conflicting_landmarks_have_visible_residual(self):
        self.project.add_pair(1,(120,40),7,(72,40))
        self.project.add_pair(1,(110,40),7,(72,40))
        self.assertGreater(max(self.project.residuals),4)

    def test_mask_rejects_player_and_hud_landmark(self):
        for point in ((82,82),(0,0)):
            with self.assertRaises(ValueError):
                self.project.add_pair(1,point,7,(72,40))

    def test_cannot_pair_same_frame(self):
        with self.assertRaises(ValueError):
            self.project.add_pair(1,(120,40),1,(72,40))

    def test_saved_project_can_reopen_and_undo(self):
        self.project.anchor(7,(48,0));self.project.undo()
        np.testing.assert_allclose(self.project.corrected,self.project.base,atol=1e-9)
        self.project.add_pair(1,(120,40),7,(72,40))
        reopened = AlignmentProject(self.source,project_file=self.project_file)
        np.testing.assert_allclose(reopened.corrected,self.project.corrected)

    def test_mismatched_source_is_rejected(self):
        self.project.save()
        with (self.source/'frames.jsonl').open('a') as stream:stream.write('\n')
        with self.assertRaises(ValueError):
            AlignmentProject(self.source,project_file=self.project_file)

    def test_source_files_never_modified_by_edit_or_export(self):
        before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.source/'tiles').glob('*.png')}
        source_hash = hashlib.sha256((self.source/'frames.jsonl').read_bytes()).hexdigest()
        self.project.anchor(7,(48.25,0))
        self.project.export(self.root/'export')
        after = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.source/'tiles').glob('*.png')}
        self.assertEqual(before,after)
        self.assertEqual(source_hash,hashlib.sha256((self.source/'frames.jsonl').read_bytes()).hexdigest())

    def test_export_contains_corrected_fractional_positions_and_map(self):
        self.project.anchor(7,(48.25,.25));out = self.root/'export'
        self.project.export(out)
        rows = json.loads((out/'corrected-placements.json').read_text())
        self.assertAlmostEqual(rows[-1]['x'],48.25,delta=.03)
        self.assertAlmostEqual(rows[-1]['y'],.25,delta=.03)
        for name in ('map.png','coverage.png','map-transparent.png','state.npz','patrol-config.json','alignment.json'):
            self.assertTrue((out/name).exists())
        status = json.loads((out/'export-status.json').read_text())
        self.assertTrue(status['completed']);self.assertFalse(status['human_review_complete'])

    def test_export_cancelled_and_existing_output_preserved(self):
        out = self.root/'export'
        with self.assertRaises(RuntimeError):
            self.project.export(out,cancelled=lambda:True)
        self.assertFalse(json.loads((out/'export-status.json').read_text())['completed'])
        with self.assertRaises(FileExistsError):
            self.project.export(out)

    def test_exclude_frame_and_reject_excluding_constraint_endpoint(self):
        self.project.set_included(2,False)
        self.assertNotIn(2,self.project.selected_ids())
        self.project.add_pair(1,(120,40),7,(72,40))
        with self.assertRaises(ValueError):
            self.project.set_included(7,False)

    def test_remove_constraints_and_fixed_origin(self):
        self.project.anchor(7,(48,0));self.project.remove_constraint('anchor',7)
        np.testing.assert_allclose(self.project.corrected,self.project.base,atol=1e-8)
        with self.assertRaises(ValueError):self.project.anchor(1,(2,0))

    def test_placement_auto_discovery_checks_all_timestamps(self):
        good = self.root/'rebuild-good';bad = self.root/'rebuild-bad';good.mkdir();bad.mkdir()
        content = (self.source/'frames.jsonl').read_text()
        (good/'frames.jsonl').write_text(content)
        rows = json.loads(json.dumps(self.rows));rows[3]['t'] += .1
        (bad/'frames.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
        self.assertEqual(matching_placements(self.source,self.root),good/'frames.jsonl')

    def test_keyframes_and_suggestion_are_valid_ids(self):
        self.assertIn(self.project.suggest_reference(7),self.project.ids)
        self.assertEqual(self.project.keyframes()[0],1)
        self.assertEqual(self.project.keyframes()[-1],7)

    def test_graph_symmetric_axes(self):
        edges = [(i,i+1,(0,0),1) for i in range(10)]
        result,_ = solve_graph(11,edges,[(0,(0,0),1000),(10,(20,-10),1000)])
        np.testing.assert_allclose(result[5],(10,-5),atol=.01)

    def test_polygon_frame_mask_does_not_affect_other_frames(self):
        shape = dict(kind='polygon',op='erase',points=[[112,40],[136,64],[112,80]])
        self.assertTrue(self.project.mask(1)[60,120])
        self.project.add_mask_shape(7,shape)
        self.assertEqual(self.project.mask(7)[60,120],0)
        self.assertTrue(self.project.mask(1)[60,120])

    def test_global_mask_and_frame_restore_precedence(self):
        cut = dict(kind='brush',op='erase',radius=8,points=[[120,60]])
        self.project.add_mask_shape(1,cut,scope='global')
        self.assertEqual(self.project.mask(7)[60,120],0)
        self.project.add_mask_shape(7,dict(cut,op='restore',radius=3))
        self.assertTrue(self.project.mask(7)[60,120])
        self.assertEqual(self.project.mask(1)[60,120],0)

    def test_restore_brush_cannot_escape_circle_or_center(self):
        self.project.add_mask_shape(7,dict(kind='brush',op='restore',radius=40,points=[[82,82],[0,0]]))
        mask = self.project.mask(7)
        self.assertEqual(mask[82,82],0);self.assertEqual(mask[0,0],0)

    def test_enlarge_circle_and_remove_center_protection_explicitly(self):
        self.assertEqual(self.project.mask(1)[82,12],0)
        self.project.set_circle(74,0)
        self.assertTrue(self.project.mask(1)[82,12])
        self.assertTrue(self.project.mask(1)[82,82])
        with self.assertRaises(ValueError):self.project.set_circle(90,0)

    def test_mask_copy_undo_and_reopen(self):
        self.project.add_mask_shape(7,dict(kind='brush',op='erase',radius=4,points=[[120,60]]))
        self.project.copy_frame_mask(7,1)
        np.testing.assert_array_equal(self.project.mask(1),self.project.mask(7))
        self.project.undo()
        self.assertTrue(self.project.mask(1)[60,120])
        reopened = AlignmentProject(self.source,project_file=self.project_file)
        np.testing.assert_array_equal(reopened.mask(7),self.project.mask(7))

    def test_mask_bitmap_import_and_clear(self):
        image = self.project.mask();image[55:66,115:126] = 0
        path = self.root/'mask.png';write_image(path,image)
        self.project.import_mask(7,path)
        self.assertEqual(self.project.mask(7)[60,120],0)
        self.project.clear_mask(7)
        self.assertTrue(self.project.mask(7)[60,120])

    def test_export_uses_expanded_circle_and_exact_cutout(self):
        self.project.set_circle(74,26)
        for fid in self.project.ids[1:]:self.project.set_included(fid,False)
        self.project.add_mask_shape(1,dict(kind='brush',op='erase',radius=5,points=[[120,60]]),scope='global')
        out = self.root/'masked-export';self.project.export(out)
        coverage = cv2.imread(str(out/'coverage.png'),cv2.IMREAD_GRAYSCALE)
        self.assertTrue(coverage[82,12])
        self.assertEqual(coverage[60,120],0)
        from modular_agent.realtime.patrol import make_vision
        config = json.loads((out/'patrol-config.json').read_text())
        _,loc,_ = make_vision(config,out/'patrol-config.json')
        self.assertIsNotNone(loc.input_mask)
        self.assertEqual(loc.input_mask[60,120],0)

    def test_landmark_on_masked_area_is_rejected(self):
        self.project.add_mask_shape(1,dict(kind='brush',op='erase',radius=8,points=[[120,40]]))
        with self.assertRaises(ValueError):self.project.add_pair(1,(120,40),7,(72,40))

    def test_existing_landmark_is_flagged_if_later_masked(self):
        self.project.add_pair(1,(120,40),7,(72,40))
        self.project.add_mask_shape(1,dict(kind='brush',op='erase',radius=8,points=[[120,40]]))
        self.assertEqual(self.project.masked_landmarks(),1)

    def test_preview_mask_does_not_modify_saved_shapes(self):
        shape = dict(kind='brush',op='erase',radius=8,points=[[120,60]])
        self.assertEqual(self.project.mask(7,extra=shape)[60,120],0)
        self.assertTrue(self.project.mask(7)[60,120])

    def manual_project(self):
        return AlignmentProject(self.source,project_file=self.root/'manual.json',from_zero=True)

    def test_from_zero_starts_empty_and_ignores_automatic_positions(self):
        project = self.manual_project()
        self.assertEqual(project.selected_ids(),[])
        np.testing.assert_array_equal(project.base,np.zeros((7,2)))
        self.assertIsNone(project.preview())

    def test_draft_move_and_landmark_do_not_auto_include_frames(self):
        project = self.manual_project()
        project.set_included(1,True)
        project.anchor(7,(48,0))
        project.add_pair(1,(120,40),7,(72,40))
        self.assertEqual(project.selected_ids(),[1])
        self.assertAlmostEqual(project.pose(7)[0],48,delta=.05)
        project.set_included(7,True)
        self.assertEqual(project.selected_ids(),[1,7])

    def test_manual_origin_does_not_change_when_earlier_frame_added(self):
        project = self.manual_project();project.set_included(7,True)
        project.anchor(1,(30,0));project.set_included(1,True)
        self.assertEqual(project.data['origin_frame'],7)
        project.anchor(1,(50,0))
        self.assertAlmostEqual(project.pose(7)[0],0,delta=.05)

    def test_manual_can_remove_all_and_reopen_without_importing_auto_frames(self):
        project = self.manual_project();project.set_included(1,True);project.set_included(1,False)
        self.assertEqual(project.selected_ids(),[])
        reopened = AlignmentProject(self.source,project_file=self.root/'manual.json')
        self.assertTrue(reopened.manual);self.assertIsNone(reopened.preview())

    def test_manual_export_only_confirmed_frames(self):
        project = self.manual_project();project.set_included(1,True)
        project.anchor(7,(48,0))
        out = self.root/'manual-export';project.export(out)
        self.assertEqual(len(json.loads((out/'corrected-placements.json').read_text())),1)
        self.assertEqual(json.loads((out/'alignment.json').read_text())['workflow'],'manual')

    def test_from_zero_cannot_overwrite_assisted_project(self):
        self.project.save()
        before = self.project_file.read_bytes()
        with self.assertRaises(ValueError):
            AlignmentProject(self.source,project_file=self.project_file,from_zero=True)
        self.assertEqual(before,self.project_file.read_bytes())

    def test_free_manual_can_move_first_layer_without_moving_others(self):
        project = self.manual_project();project.set_included(1,True);project.set_included(7,True)
        project.anchor(1,(45,-20))
        np.testing.assert_array_equal(project.pose(1),(45,-20))
        np.testing.assert_array_equal(project.pose(7),(0,0))
        self.assertEqual(project.iterations,0)

    def test_optional_landmark_alignment_does_not_constrain_later_drag(self):
        project = self.manual_project();project.set_included(1,True)
        project.add_pair(1,(120,40),7,(72,40))
        self.assertAlmostEqual(project.pose(7)[0],48)
        project.anchor(1,(30,0))
        self.assertAlmostEqual(project.pose(7)[0],48)
        self.assertAlmostEqual(project.residuals[0],30)

    def test_manual_layer_order_and_transparent_masks(self):
        project = self.manual_project();project.set_included(1,True);project.set_included(7,True)
        image = project.preview()
        np.testing.assert_array_equal(image[60,120],project.tile(7)[60,120])
        project.layer_order(1,front=True)
        np.testing.assert_array_equal(project.preview()[60,120],project.tile(1)[60,120])
        project.add_mask_shape(1,dict(kind='brush',op='erase',radius=5,points=[[120,60]]))
        np.testing.assert_array_equal(project.preview()[60,120],project.tile(7)[60,120])

    def test_legacy_manual_migration_preserves_backup_and_independent_poses(self):
        project = self.manual_project();project.set_included(1,True);project.set_included(7,True)
        project.anchor(7,(48,0))
        path = self.root/'manual.json'
        data = json.loads(path.read_text());data.pop('manual_engine')
        atomic_json(path,data);before = path.read_bytes()
        reopened = AlignmentProject(self.source,project_file=path)
        self.assertTrue(reopened.free_manual)
        other = reopened.pose(7)
        reopened.anchor(1,(20,0))
        np.testing.assert_array_equal(reopened.pose(7),other)
        self.assertEqual(path.with_name('manual.before-free.json').read_bytes(),before)


if __name__=='__main__':
    unittest.main()
