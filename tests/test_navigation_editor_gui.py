from types import SimpleNamespace
from unittest.mock import patch
import unittest
from test_navigation_annotations import NavigationFixture
from modular_agent.realtime.navigation_editor import NavigationEditor


class EditorTests(NavigationFixture,unittest.TestCase):
    def test_teaching_replay_and_fused_mode_are_separate_explicit_launches(self):
        self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')
        self.project.add_route_stop([10,20]);self.project.add_route_stop([100,20])
        editor=NavigationEditor(self.project,visible=False)
        try:
            editor.plan_route()
            with patch('subprocess.Popen') as launch:
                editor.follow_preview(teach=True);args=launch.call_args.args[0]
                self.assertIn('--teach-route',args);self.assertNotIn('--live-route',args)
            editor.route_process=None;editor.estimator.set('融合（巡航短暂丢帧预测）')
            with patch('subprocess.Popen') as launch:
                editor.follow_preview(live=True,replay=True);args=launch.call_args.args[0]
                self.assertIn('--live-route',args);self.assertIn('--replay-demo',args)
                self.assertEqual(args[args.index('--estimator')+1],'fused')
            editor.show_comparison()
            self.assertIn('不是物理真值',editor.report.get('1.0','end'))
        finally:editor.close()

    def test_motion_probe_is_explicit_setup_with_matching_map_and_mask(self):
        self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')
        self.project.add_route_stop([10,20]);self.project.add_route_stop([100,20])
        editor=NavigationEditor(self.project,visible=False)
        try:
            editor.plan_route()
            with patch('subprocess.Popen') as launch:
                editor.motion_probe();args=launch.call_args.args[0]
                self.assertIn('modular_agent.realtime.motion_probe',args)
                self.assertIn('--config',args);self.assertIn('--walk-mask',args)
                self.assertNotIn('--live',args)
        finally:editor.close()

    def test_live_button_exports_and_passes_explicit_input_flags(self):
        self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')
        self.project.add_route_stop([10,20]);self.project.add_route_stop([100,20])
        editor=NavigationEditor(self.project,visible=False)
        try:
            editor.plan_route()
            with patch('subprocess.Popen') as launch:
                editor.follow_preview(live=True)
                args=launch.call_args.args[0]
                self.assertIn('--live-route',args);self.assertNotIn('--auto-calibrate',args)
                self.assertIn('--planned-route',args);self.assertIn('--config',args)
            with patch('subprocess.Popen') as launch:
                editor.follow_preview()
                self.assertNotIn('--live-route',launch.call_args.args[0])
        finally:editor.close()

    def test_hidden_editor_add_route_jump_polygon_and_zoom(self):
        editor = NavigationEditor(self.project,visible=False)
        try:
            event = lambda x,y:SimpleNamespace(x=x,y=y)
            editor.click(event(20,20));treasure = editor.selected
            editor.mode.set('route');editor.click(event(20,20));editor.click(event(80,60))
            self.assertEqual(self.project.route['nodes'][0],treasure)
            self.assertEqual(len(self.project.route['nodes']),2)
            editor.mode.set('jump');editor.click(event(30,30));editor.click(event(50,40))
            self.assertEqual(len(self.project.data['jumps']),1)
            editor.mode.set('blocked')
            for x,y in [(40,10),(60,10),(60,40)]:editor.click(event(x,y))
            editor.finish_polygon();self.assertEqual(len(self.project.data['regions']),1)
            editor.set_zoom(2);self.assertEqual((editor.photo.width(),editor.photo.height()),(240,200))
            self.assertEqual(self.project.find(treasure)[1]['xy'],[20,20])
            editor.save();self.assertEqual(len(self.project.history)>0,True)
        finally:editor.close()

    def test_route_delete_is_local_and_pending_properties_save(self):
        identifier = self.project.add_point([20,20]);self.project.add_to_route(identifier)
        editor = NavigationEditor(self.project,visible=False)
        try:
            editor.selected = identifier;editor.refresh();editor.name.set('新的宝藏名')
            self.assertTrue(editor.save())
            self.assertEqual(self.project.find(identifier)[1]['name'],'新的宝藏名')
            editor.stops.selection_set(0)
            with patch.object(editor.root,'focus_get',return_value=editor.stops):editor.keyboard_delete()
            self.assertEqual(self.project.route['nodes'],[])
            self.assertEqual(len(self.project.data['points']),1)
            editor.undo();self.assertEqual(self.project.route['nodes'],[identifier])
        finally:editor.close()

    def test_point_drag_is_undoable_and_invalid_draft_keeps_editor_alive(self):
        identifier = self.project.add_point([20,20])
        editor = NavigationEditor(self.project,visible=False)
        try:
            editor.mode.set('select');editor.click(SimpleNamespace(x=20,y=20))
            editor.drag(SimpleNamespace(x=60,y=40));editor.release(None)
            self.assertEqual(self.project.find(identifier)[1]['xy'],[60,40])
            editor.undo();self.assertEqual(self.project.find(identifier)[1]['xy'],[20,20])
            editor.mode.set('blocked');editor.draft = [[10,10],[20,20],[30,30]]
            editor.finish_polygon();self.assertEqual(self.project.data['regions'],[])
            self.assertTrue(editor.draft);self.assertFalse(editor.closed)
        finally:editor.close()

    def test_planning_preview_is_invalidated_by_annotation_change(self):
        self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')
        self.project.add_route_stop([10,20]);self.project.add_route_stop([100,20])
        editor = NavigationEditor(self.project,visible=False)
        try:
            editor.plan_route();self.assertIsNotNone(editor.plan)
            editor.mode.set('treasure');editor.click(SimpleNamespace(x=20,y=60))
            self.assertIsNone(editor.plan)
        finally:editor.close()

    def test_reversing_jump_requires_manual_reverification(self):
        identifier = self.project.add_jump([20,20],[50,40]);self.project.find(identifier)[1]['verified'] = True
        editor = NavigationEditor(self.project,visible=False)
        try:
            editor.selected = identifier;editor.refresh();editor.reverse_jump()
            jump = self.project.find(identifier)[1]
            self.assertEqual(jump['start'],[50,40]);self.assertFalse(jump['verified'])
        finally:editor.close()


if __name__=='__main__':unittest.main()
