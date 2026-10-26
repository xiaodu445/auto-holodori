import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from modular_agent.domains.hololive_dreams.navigation_annotations import NavigationProject,digest
from modular_agent.domains.hololive_dreams.patrol_vision import write_image


class NavigationFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_image(self.root/'source.png',np.full((100,120,3),150,np.uint8))
        write_image(self.root/'coverage.png',np.full((100,120),255,np.uint8))
        (self.root/'config.json').write_text(json.dumps(dict(reference='source.png',coverage='coverage.png')))
        self.project = NavigationProject.create(self.root/'config.json',self.root/'project')


class NavigationTests(NavigationFixture,unittest.TestCase):

    def test_frozen_map_and_empty_initial_annotations(self):
        self.assertEqual(self.project.data['points'],[])
        self.assertEqual(self.project.route['nodes'],[])
        self.assertEqual(digest(self.root/'source.png'),digest(self.project.map_path))

    def test_renaming_point_preserves_route_reference_and_undo(self):
        identifier = self.project.add_point([10,20]);self.project.add_to_route(identifier)
        self.project.change(lambda:self.project.find(identifier)[1].update(name='喷泉边'))
        self.assertEqual(self.project.route_points()[0]['name'],'喷泉边')
        self.project.undo();self.assertEqual(self.project.route['nodes'],[identifier])

    def test_delete_point_removes_all_route_references_and_undo_restores(self):
        identifier = self.project.add_point([10,20]);self.project.add_to_route(identifier);self.project.add_to_route(identifier)
        self.project.delete(identifier);self.assertEqual(self.project.route['nodes'],[])
        self.project.undo();self.assertEqual(self.project.route['nodes'],[identifier,identifier])

    def test_combined_new_route_stop_has_one_undo(self):
        self.project.add_route_stop([10,20]);self.project.undo()
        self.assertEqual(self.project.data['points'],[]);self.assertEqual(self.project.route['nodes'],[])

    def test_directional_jump_persists_without_adding_reverse_edge(self):
        self.project.add_jump([10,20],[40,50]);self.project.save()
        loaded = NavigationProject(self.project.path)
        self.assertEqual(len(loaded.data['jumps']),1)
        self.assertEqual(loaded.data['jumps'][0]['direction'],'start_to_end')
        self.assertEqual(loaded.data['jumps'][0]['start'],[10,20])

    def test_blocked_overrides_walk_and_route_warns(self):
        self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')
        self.project.add_region([[40,0],[60,0],[60,99],[40,99]],'blocked')
        self.project.add_route_stop([10,50]);self.project.add_route_stop([100,50])
        walk,blocked = self.project.masks()
        self.assertEqual(walk[50,50],0);self.assertEqual(blocked[50,50],255)
        self.assertTrue(any('禁行' in w for w in self.project.route_report()['warnings']))

    def test_no_walk_regions_is_draft_not_verified_navigation(self):
        self.project.add_route_stop([10,10]);self.project.add_route_stop([30,10])
        report = self.project.route_report();self.assertFalse(report['navigation_verified'])
        self.assertTrue(report['warnings']);self.assertEqual(report['length_pixels'],20)
        self.project.route['loop'] = True;self.assertEqual(self.project.route_report()['length_pixels'],40)

    def test_geometric_order_preserves_first_and_treasure_ids(self):
        for xy in ([10,10],[100,10],[20,10],[30,10]):self.project.add_route_stop(xy)
        before = list(self.project.route['nodes']);self.project.suggest_order()
        self.assertEqual(self.project.route['nodes'],[before[0],before[2],before[3],before[1]])
        self.project.undo();self.assertEqual(self.project.route['nodes'],before)

    def test_invalid_coordinates_and_polygons_do_not_mutate(self):
        for xy in ([float('nan'),3],[-1,0],[120,50]):
            with self.assertRaises(ValueError):self.project.add_point(xy)
        with self.assertRaises(ValueError):self.project.add_region([[1,1],[2,2],[3,3]],'blocked')
        with self.assertRaises(ValueError):self.project.add_jump([10,10],[10,10])
        self.assertFalse(self.project.data['points']);self.assertFalse(self.project.data['regions']);self.assertFalse(self.project.data['jumps'])

    def test_source_change_does_not_alter_frozen_project_but_local_change_is_rejected(self):
        write_image(self.root/'source.png',np.full((100,120,3),200,np.uint8))
        NavigationProject(self.project.path)
        write_image(self.project.map_path,np.full((100,120,3),200,np.uint8))
        with self.assertRaises(ValueError):NavigationProject(self.project.path)

    def test_export_is_self_contained_and_preserves_original(self):
        signature = digest(self.root/'source.png')
        self.project.add_point([10,20]);self.project.add_jump([30,30],[50,30])
        first = self.project.export();second = self.project.export()
        self.assertNotEqual(first,second)
        exported = NavigationProject(first/'navigation.json')
        self.assertEqual(len(exported.data['points']),1)
        self.assertTrue((first/'annotations.png').is_file())
        self.assertEqual(digest(self.root/'source.png'),signature)
        self.assertFalse(json.loads((first/'route.json').read_text(encoding='utf-8'))['reviewed'])


if __name__=='__main__':unittest.main()
