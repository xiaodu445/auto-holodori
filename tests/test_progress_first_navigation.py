import math
import unittest
import numpy as np
from modular_agent.domains.hololive_dreams.camera_navigation import CameraWRouteFollower,CameraHeading,CameraTurn,angle_error
from modular_agent.domains.hololive_dreams.patrol import Position


class ProgressFirstTests(unittest.TestCase):
    def follower(self,points=None):
        return CameraWRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='walk',points=points or [[180,100]])]),
            np.full((240,240),255,np.uint8),degrees_per_count=.071,continuous=True,fast_turns=True,progress_first=True)

    def step(self,f,t,x=50,y=100,yaw=0,source='reference_cone',**kw):
        return f.step(Position(x,y,t),round(t*10000)+1,t,heading=CameraHeading(yaw,t,True,source,1),**kw)

    def test_starts_forward_before_perfect_alignment_and_corrects_in_motion(self):
        f=self.follower();self.step(f,0,yaw=20)
        d=self.step(f,.2,yaw=20)
        self.assertEqual(d.kind,'cruise');self.assertLess(d.mouse_dx,0)
        self.assertEqual(d.counts_per_second,2400)
        f.dispatched(d,.2)
        self.assertEqual(self.step(f,.4,x=55,yaw=35).kind,'cruise')

    def test_logged_small_reverse_after_fast_turn_does_not_exit(self):
        # Failure tail: pose (322,574), target (287.5,574.75), camera 175->171
        # after +34 counts, while earlier negative turns may still be visible.
        f=CameraWRouteFollower(dict(planning='annotation_astar',segments=[dict(kind='walk',points=[[287.5,574.75]])]),
            np.full((700,700),255,np.uint8),degrees_per_count=.07091091775,continuous=True,fast_turns=True,progress_first=True)
        f.settling=False;f.last_heading=175
        from modular_agent.domains.hololive_dreams.camera_navigation import CruiseDecision
        f.dispatched(CruiseDecision(mouse_dx=34),13.16)
        d=self.step(f,13.19178,x=322,y=574,yaw=171)
        self.assertEqual(d.kind,'cruise');self.assertGreater(d.mouse_dx,0)

    def test_partial_fast_turn_or_sensor_change_recomputes_not_response_failure(self):
        for yaw,source in ((20,'reference_cone'),(18,'paired_boundary_cone'),(25,'reference_cone')):
            f=self.follower();f.settling=False;f.last_heading=90;f.last_heading_source='reference_cone';f.last_heading_t=0
            f.dispatched(CameraTurn(mouse_dx=-1077,counts_per_second=7200),.2)
            d=self.step(f,.4,yaw=yaw,source=source)
            self.assertEqual(d.kind,'cruise')

    def test_keeps_correcting_while_position_advances_despite_camera_model_error(self):
        f=self.follower();self.step(f,0,yaw=5);d=self.step(f,.2,yaw=5);f.dispatched(d,.2)
        for t,x in ((.5,55),(1.5,65),(2.5,80)):
            d=self.step(f,t,x=x,yaw=5)
            self.assertEqual(d.kind,'cruise');f.dispatched(d,t)

    def test_real_stall_popup_cancel_and_mask_still_stop(self):
        f=self.follower();self.step(f,0);d=self.step(f,.2);f.dispatched(d,.2)
        self.assertEqual(self.step(f,5.3).reason,'stuck_no_visual_progress')
        f=self.follower();self.assertEqual(self.step(f,0,free_scene=False).kind,'stop')
        f=self.follower();self.assertEqual(self.step(f,0,cancelled=True).kind,'stop')
        f=self.follower();f.mask[100,80]=0;self.step(f,0)
        self.assertEqual(self.step(f,.2).kind,'stop')

    def test_lagging_camera_simulation_reaches_both_waypoints(self):
        f=self.follower([[180,100],[180,180]])
        xy=np.array([50.,100.]);yaw=70.;desired_yaw=yaw;t=0.;cruises=0
        for frame in range(1,1800):
            yaw=(yaw+angle_error(desired_yaw,yaw)*.65)%360
            d=f.step(Position(*xy,t),frame,t,heading=CameraHeading(yaw,t,True,'reference_cone'))
            if d.kind=='stop':break
            if d.kind in ('turn','cruise'):
                desired_yaw=(desired_yaw+d.mouse_dx*.071)%360
                f.dispatched(d,t+(.01 if d.kind=='turn' else 0))
            if d.kind in ('cruise','move'):
                duration=.15 if d.kind=='cruise' else d.duration
                xy+=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])*28.5*duration
                if d.kind=='move':f.dispatched(d,t+d.duration)
                if d.kind=='cruise':cruises+=1
            t+=.15
        self.assertEqual(d.reason,'route_traversed_collection_unverified')
        self.assertGreater(cruises,20)


if __name__=='__main__':unittest.main()
