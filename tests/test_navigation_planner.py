import json
from pathlib import Path
import unittest
import numpy as np
from test_navigation_annotations import NavigationFixture
from modular_agent.domains.hololive_dreams.navigation_planner import plan_project,clear_line,RouteFollower,WalkPlanner
from modular_agent.domains.hololive_dreams.patrol import Position,MotionCalibration


class PlannerTests(NavigationFixture,unittest.TestCase):
    def walk(self):self.project.add_region([[0,0],[119,0],[119,99],[0,99]],'walkable')

    def endpoints(self,start=(10,10),end=(100,10)):
        self.project.add_route_stop(start);self.project.add_route_stop(end)

    def test_detour_avoids_wall_and_simplification_never_cuts_it(self):
        self.walk();self.endpoints();self.project.add_region([[40,0],[60,0],[60,70],[40,70]],'blocked')
        plan = plan_project(self.project,cell=2,clearance=1)
        self.assertGreater(plan['length_pixels'],90);self.assertGreater(len(plan['points']),2)
        mask,_ = self.project.masks();planner = WalkPlanner(mask,cell=2,clearance=1)
        self.assertTrue(all(clear_line(planner.mask,a,b) for s in plan['segments'] for a,b in zip(s['points'],s['points'][1:])))

    def test_unknown_unmarked_area_does_not_become_walkable(self):
        self.endpoints()
        with self.assertRaisesRegex(ValueError,'可走区'):plan_project(self.project)

    def test_disconnected_regions_and_blocked_endpoint_report_failure(self):
        self.walk();self.endpoints();self.project.add_region([[40,0],[60,0],[60,99],[40,99]],'blocked')
        with self.assertRaises(ValueError):plan_project(self.project,cell=2,clearance=0)
        self.project.route['nodes'].reverse()
        self.project.find(self.project.route['nodes'][0])[1]['xy'] = [50,50]
        with self.assertRaisesRegex(ValueError,'途经点'):plan_project(self.project,cell=2,clearance=0)

    def test_only_verified_forward_jump_can_connect_islands(self):
        self.walk();self.endpoints((10,50),(100,50))
        self.project.add_region([[40,0],[60,0],[60,99],[40,99]],'blocked')
        identifier = self.project.add_jump([30,50],[70,50])
        with self.assertRaises(ValueError):plan_project(self.project,cell=2,clearance=0,allow_jumps=True)
        self.project.find(identifier)[1]['verified'] = True
        plan = plan_project(self.project,cell=2,clearance=0,allow_jumps=True)
        self.assertTrue(plan['requires_jump_execution']);self.assertEqual(sum(s['kind']=='jump' for s in plan['segments']),1)
        self.project.route['nodes'].reverse()
        with self.assertRaises(ValueError):plan_project(self.project,cell=2,clearance=0,allow_jumps=True)

    def test_loop_returns_to_start_and_export_has_bound_mask(self):
        self.walk();self.endpoints();self.project.route['loop'] = True
        plan = plan_project(self.project,cell=2,clearance=1)
        self.assertEqual(plan['points'][0],plan['points'][-1])
        folder = self.project.export(plan)
        self.assertTrue((folder/'planning-mask.png').exists());self.assertTrue((folder/'patrol-config.json').exists())
        exported = json.loads((folder/'planned-route.json').read_text(encoding='utf-8'))
        self.assertEqual(exported['map_sha256'],self.project.data['map']['sha256'])
        self.assertFalse(exported['reviewed'])

    def test_export_rejects_stale_plan(self):
        self.walk();self.endpoints();plan = plan_project(self.project)
        self.project.add_point([20,40])
        with self.assertRaisesRegex(ValueError,'重新规划'):self.project.export(plan)

    def test_clearance_and_diagonal_corner_guard(self):
        mask = np.full((20,20),255,np.uint8);mask[10,11] = 0
        self.assertFalse(clear_line(mask,(10,10),(11,11)))
        with self.assertRaises(ValueError):WalkPlanner(mask,cell=0)


class FollowerTests(unittest.TestCase):
    def plan(self,segments):return dict(planning='annotation_astar',segments=segments)

    def test_freshness_unknown_scene_and_cancel_never_propose_motion(self):
        follower = RouteFollower(self.plan([dict(kind='walk',points=[[10,10],[50,10]])]),np.full((80,80),255,np.uint8))
        self.assertEqual(follower.step(Position(0,0,0),1,2).kind,'wait')
        self.assertEqual(follower.step(Position(0,0,2),2,2,free_scene=False).kind,'wait')
        self.assertEqual(follower.step(Position(0,0,2),3,2,cancelled=True).kind,'stop')

    def test_waypoint_progress_and_short_calibrated_proposal(self):
        motion = MotionCalibration(dict(w=(0,-100),s=(0,100),a=(-100,0),d=(100,0)))
        follower = RouteFollower(self.plan([dict(kind='walk',points=[[10,10],[50,10]])]),np.full((80,80),255,np.uint8),motion)
        self.assertEqual(follower.step(Position(10,10,0),1,0).reason,'waypoint_observed')
        decision = follower.step(Position(10,10,.1),2,.1)
        self.assertEqual(decision.kind,'move');self.assertLessEqual(decision.duration,.12)
        self.assertEqual(follower.step(Position(50,10,.2),3,.2).reason,'waypoint_observed')
        self.assertEqual(follower.step(Position(50,10,.3),4,.3).kind,'stop')

    def test_jump_is_manual_and_requires_two_fresh_landing_frames(self):
        follower = RouteFollower(self.plan([dict(kind='jump',points=[[10,10],[50,10]])]),np.full((80,80),255,np.uint8))
        self.assertEqual(follower.step(Position(10,10,0),1,0).reason,'manual_jump_required')
        self.assertEqual(follower.step(Position(50,10,.1),2,.1).reason,'manual_jump_required')
        self.assertEqual(follower.step(Position(50,10,.1),2,.1).reason,'fresh_localization_required')
        self.assertEqual(follower.step(Position(50,10,.2),3,.2).reason,'manual_jump_required')
        self.assertEqual(follower.step(Position(50,10,.3),4,.3).reason,'jump_landing_observed')

    def test_obstacle_or_missing_calibration_prevents_motion(self):
        mask = np.full((80,80),255,np.uint8)
        follower = RouteFollower(self.plan([dict(kind='walk',points=[[50,10]])]),mask)
        self.assertEqual(follower.step(Position(10,10,0),1,0).reason,'motion_calibration_required')
        mask[:,30] = 0
        self.assertEqual(follower.step(Position(10,10,.1),2,.1).reason,'current_position_requires_replan')


if __name__=='__main__':unittest.main()
