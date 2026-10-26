import math
from types import SimpleNamespace
import unittest
import cv2
import numpy as np
from modular_agent.core import Outcome
from modular_agent.domains.hololive_dreams.patrol import Position,Decision
from modular_agent.domains.hololive_dreams.camera_navigation import (
    CameraWRouteFollower,CameraHeading,CameraTurn,reference_cone,VisualCameraHeading,angle_error)
from modular_agent.realtime.camera_navigation import GuardedCameraExecutor,camera_calibration,RouteFrameGuard


class CameraControllerTests(unittest.TestCase):
    def follower(self,segments=None):
        return CameraWRouteFollower(dict(planning='annotation_astar',segments=segments or [dict(kind='walk',points=[[120,100]])]),
            np.full((220,220),255,np.uint8),degrees_per_count=.071)

    def step(self,f,t,x=50,y=100,yaw=0,**kwargs):
        heading=kwargs.pop('heading',CameraHeading(yaw,t,True,'test',1))
        return f.step(Position(x,y,t),round(t*1000)+1,t,heading=heading,**kwargs)

    def ready(self,f,x=50,yaw=0):
        self.step(f,0,x=x,yaw=yaw)
        return self.step(f,.2,x=x,yaw=yaw)

    def test_turn_then_only_w_after_visual_alignment(self):
        f=self.follower();turn=self.ready(f,yaw=90)
        self.assertEqual(turn.kind,'turn');self.assertLess(turn.mouse_dx,0);self.assertFalse(turn.keys)
        f.dispatched(turn,.4)
        next_turn=self.step(f,.8,yaw=90+turn.mouse_dx*.071)
        self.assertEqual(next_turn.kind,'turn')
        f.pending_turn=None
        move=self.step(f,1,yaw=0)
        self.assertEqual(move.keys,('w',));self.assertLessEqual(move.duration,.30)

    def test_fast_cruise_keeps_precise_final_approach_and_stable_stop(self):
        f=self.follower();move=self.ready(f)
        self.assertEqual(move.duration,.30)
        f.dispatched(move,.5)
        self.assertEqual(self.step(f,.76,x=60).reason,'confirming_stop_before_turn')
        self.assertEqual(self.step(f,.9,x=60).kind,'move')
        near=self.ready(self.follower(),x=114)
        f.dispatched(near,1)
        self.assertAlmostEqual(f.ready_at,1.6)
        self.assertEqual(self.step(f,1.4,x=118).reason,'coasting')

    def test_larger_turn_still_needs_visual_response(self):
        f=self.follower();turn=self.ready(f,yaw=90)
        self.assertEqual(abs(turn.mouse_dx),72)
        f.dispatched(turn,.5)
        self.assertAlmostEqual(f.ready_at,.56)
        self.assertEqual(self.step(f,.7,yaw=90).reason,'camera_turn_response_wait')
        self.assertEqual(self.step(f,1.6,yaw=90).reason,'camera_turn_not_observed')

    def test_coasting_prevents_turn_and_false_arrival(self):
        f=self.follower();move=self.ready(f);f.dispatched(move,.44)
        self.assertEqual(self.step(f,.6,x=120).reason,'coasting');self.assertEqual(f.index,0)
        self.step(f,1.1,x=120);self.step(f,1.3,x=120);self.step(f,1.5,x=120)
        self.assertEqual(f.index,1)

    def test_shorter_w_pulse_near_goal_and_no_sideways_keys(self):
        far=self.ready(self.follower(),x=60);near=self.ready(self.follower(),x=114)
        self.assertLess(near.duration,far.duration)
        self.assertEqual(near.keys,('w',))

    def test_dropped_turn_stops_without_blind_repeats(self):
        f=self.follower();turn=self.ready(f,yaw=90);f.dispatched(turn,.4)
        self.assertEqual(self.step(f,.8,yaw=90).kind,'wait')
        self.assertEqual(self.step(f,1.5,yaw=90).reason,'camera_turn_not_observed')

    def test_wrong_turn_direction_stops(self):
        f=self.follower();turn=self.ready(f,yaw=90);f.dispatched(turn,.4)
        self.assertEqual(self.step(f,.8,yaw=95).reason,'camera_turn_direction_mismatch')

    def test_unknown_heading_never_drives_and_times_out(self):
        f=self.follower();self.ready(f)
        d=self.step(f,.4,heading=CameraHeading(0,.4))
        self.assertEqual(d.kind,'turn');self.assertFalse(d.keys)
        self.assertEqual(self.step(f,9,heading=CameraHeading(0,9)).reason,'camera_heading_unavailable')

    def test_stale_position_popup_and_cancel_block_w(self):
        f=self.follower()
        self.assertEqual(f.step(Position(50,100,0),1,1,heading=CameraHeading(0,1,True)).kind,'wait')
        self.assertEqual(self.step(f,2,free_scene=False).kind,'stop')
        f=self.follower();self.assertEqual(self.step(f,0,cancelled=True).kind,'stop')

    def test_w_jump_space_only_once_and_fresh_landing_confirmation(self):
        f=self.follower([dict(kind='jump',points=[[50,100],[90,100]],verified=True)])
        d=self.ready(f);self.assertEqual(d.keys,('w','space'));f.dispatched(d,.32)
        self.assertEqual(self.step(f,.6,x=65).keys,('w',))
        self.step(f,.9,x=90);self.step(f,1.1,x=90)
        self.assertEqual(f.index,1)

    def test_dropped_jump_has_no_space_retry(self):
        f=self.follower([dict(kind='jump',points=[[50,100],[90,100]],verified=True)])
        d=self.ready(f);f.dispatched(d,.32)
        self.assertNotIn('space',self.step(f,.6).keys)
        self.assertEqual(self.step(f,2.4).reason,'jump_landing_timeout_no_retry')

    def test_map_mask_blocks_coast_projection(self):
        f=self.follower();f.mask[100,55]=0
        self.assertEqual(self.ready(f).kind,'stop')

    def test_dropped_w_cannot_continue_forever(self):
        f=self.follower();d=self.ready(f);f.dispatched(d,.44)
        self.step(f,1.1);self.step(f,1.3)
        self.assertEqual(self.step(f,5.5).reason,'stuck_no_visual_progress')

    def test_simulated_route_only_uses_w_and_mouse(self):
        f=self.follower([dict(kind='walk',points=[[120,100],[120,150],[60,150]])])
        xy=np.array([50.,100.]);yaw=90.;t=0.;moves=0;turns=0
        for frame in range(1,1800):
            d=f.step(Position(*xy,t),frame,t,heading=CameraHeading(yaw,t,True))
            if d.kind=='stop':break
            if d.kind=='turn':
                yaw=(yaw+d.mouse_dx*.071)%360;f.dispatched(d,t+d.duration);turns+=1
            elif d.kind=='move':
                self.assertEqual(d.keys,('w',))
                xy+=np.array([math.cos(math.radians(yaw)),math.sin(math.radians(yaw))])*28.5*d.duration
                f.dispatched(d,t+d.duration);moves+=1
            t+=.25
        self.assertEqual(d.reason,'route_traversed_collection_unverified')
        self.assertGreater(moves,5);self.assertGreater(turns,5)


class ConeTests(unittest.TestCase):
    def test_static_reference_does_not_switch_to_short_temporal_fit(self):
        from unittest.mock import patch
        reader=VisualCameraHeading(np.full((220,220,3),150,np.uint8))
        image=np.full((164,164,3),150,np.uint8)
        with patch('modular_agent.domains.hololive_dreams.camera_navigation.reference_cone',return_value=(239.,.94)), patch(
                'modular_agent.domains.hololive_dreams.camera_navigation.camera_headings',
                side_effect=lambda frames:([159.]*len(frames),[dict(fit_mse=.03)]*len(frames))) as temporal:
            for i in range(10):result=reader.read(image,Position(100,100,i*.1),i*.1)
            self.assertTrue(result.valid)
            self.assertEqual(result.degrees,239)
            self.assertEqual(result.source,'reference_cone')
            temporal.assert_not_called()
        with patch('modular_agent.domains.hololive_dreams.camera_navigation.reference_cone',return_value=(None,0)), patch(
                'modular_agent.domains.hololive_dreams.camera_navigation.camera_headings',
                return_value=([159.]*10,[dict(fit_mse=.03)]*10)):
            self.assertFalse(reader.read(image,Position(100,100,1.1),1.1).valid)

    def test_archived_w_frames_keep_camera_distinct_from_pointer(self):
        import json
        from modular_agent.realtime.patrol import DATA
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        folder=DATA/'w-camera-regression';source=json.loads((folder/'source.json').read_text())
        directions=[]
        for item in source['frames']:
            n=item['frame'];degree,_=reference_cone(read_image(folder/f'{n:06d}-live.png'),read_image(folder/f'{n:06d}-reference.png'),read_image(folder/f'{n:06d}-coverage.png')[:,:,0])
            self.assertIsNotNone(degree);directions.append(degree)
        self.assertLess(max(directions)-min(directions),5)
        self.assertLess(abs(angle_error(float(np.median(directions)),source['motion_direction_degrees'])),6)
    def test_reference_cone_ignores_static_yellow_ground_and_actor(self):
        rng=np.random.default_rng(78);background=rng.integers(70,170,(164,164,3),np.uint8)
        yy,xx=np.mgrid[:164,:164];angle=np.rad2deg(np.arctan2(yy-82,xx-82))
        frame=background.copy();sector=np.abs((angle-140+180)%360-180)<=46
        frame[:,:,2]+=sector.astype(np.uint8)*25;frame[:,:,0]-=sector.astype(np.uint8)*15
        frame[60:90,78:86]=255
        result,confidence=reference_cone(frame,background,np.full((164,164),255,np.uint8))
        self.assertLess(abs(angle_error(result,140)),2);self.assertGreater(confidence,.8)
        self.assertIsNone(reference_cone(background,background,np.full((164,164),255,np.uint8))[0])

    def test_unknown_reference_coverage_never_invents_heading(self):
        image=np.full((164,164,3),150,np.uint8)
        self.assertIsNone(reference_cone(image,image,np.zeros((164,164),np.uint8))[0])
        reader=VisualCameraHeading(np.full((220,220,3),150,np.uint8))
        self.assertFalse(reader.read(image,Position(100,100,0,valid=False),0).valid)


class CameraExecutorTests(unittest.TestCase):
    def test_expensive_turn_guards_finish_early_and_report_actual_counts(self):
        c=self.computer();clock=[.16]
        def check():
            clock[0]+=.035
            if clock[0]>.5:raise RuntimeError('stale_or_blocked_scene')
        executor=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        command=executor.prepare(CameraTurn(mouse_dx=72),observed_at=0)
        self.assertTrue(executor.execute(command,observed_at=0))
        self.assertLess(clock[0],.5)
        actual=sum(a.arguments['dx'] for a in c.events)
        self.assertLess(actual,command.mouse_dx)
        self.assertEqual(executor.last_decision.mouse_dx,actual)
        self.assertFalse(c.keys)

    def test_slow_capture_guard_does_not_regrab_on_every_mouse_step(self):
        c=self.computer();clock=[.20];grabs=[];bounds=(0,0,1259,708)
        def grab(roi):
            grabs.append(clock[0]);clock[0]+=.02
            return None,bounds
        capture=SimpleNamespace(bounds=lambda:bounds,grab=grab)
        gate=SimpleNamespace(hud=SimpleNamespace(read=lambda image:(True,1)),enabled=lambda image:True)
        guard=RouteFrameGuard(capture,bounds,gate,lambda:False,clock=lambda:clock[0]);guard.update(0,True)
        executor=GuardedCameraExecutor(c,guard,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        command=executor.prepare(CameraTurn(mouse_dx=48),observed_at=0)
        self.assertTrue(executor.execute(command,observed_at=0))
        self.assertLess(clock[0],.5);self.assertLessEqual(len(grabs),4)
        actual=sum(a.arguments['dx'] for a in c.events)
        self.assertLessEqual(actual,command.mouse_dx)
        self.assertGreater(actual,0)
        self.assertEqual(actual,executor.last_decision.mouse_dx)

    def test_old_frame_is_deferred_and_turn_uses_remaining_fresh_budget(self):
        c=self.computer();clock=[.46]
        executor=GuardedCameraExecutor(c,lambda:None,clock=lambda:clock[0])
        self.assertIsNone(executor.prepare(CameraTurn(mouse_dx=48),observed_at=0))
        clock[0]=.26;command=executor.prepare(CameraTurn(mouse_dx=48),observed_at=0)
        self.assertLess(command.mouse_dx,48);self.assertGreaterEqual(command.mouse_dx,16)
        self.assertFalse(c.events)

    def test_partial_mouse_input_is_counted_when_focus_guard_aborts(self):
        c=self.computer();clock=[0.]
        def check():
            if clock[0]>.025:raise RuntimeError('focus_lost')
        executor=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        with self.assertRaises(RuntimeError):executor.execute(CameraTurn(mouse_dx=48),observed_at=0)
        self.assertGreater(executor.dispatched_actions,0)

    def test_hud_refresh_cannot_extend_semantic_frame_age_or_bypass_disabled(self):
        clock=[.2];bounds=(0,0,100,100)
        capture=SimpleNamespace(bounds=lambda:bounds,grab=lambda roi:(None,bounds))
        gate=SimpleNamespace(hud=SimpleNamespace(read=lambda im:(True,1)),enabled=lambda im:False)
        guard=RouteFrameGuard(capture,bounds,gate,lambda:False,clock=lambda:clock[0]);guard.update(0,True)
        with self.assertRaisesRegex(RuntimeError,'disabled'):guard()
        gate.enabled=lambda im:True;clock[0]=.3;guard()
        clock[0]=.51
        with self.assertRaisesRegex(RuntimeError,'stale'):guard()

    def test_live_preview_wires_camera_controller_without_wasd_probe(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import patch
        from modular_agent.realtime.patrol import preview
        from modular_agent.domains.hololive_dreams.navigation_annotations import digest
        from modular_agent.domains.hololive_dreams.patrol_vision import write_image
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);reference=np.full((220,220,3),150,np.uint8)
            write_image(folder/'map.png',reference);write_image(folder/'mask.png',np.full((220,220),255,np.uint8))
            config=dict(reference='map.png');(folder/'config.json').write_text(json.dumps(config))
            plan=dict(planning='annotation_astar',map_sha256=digest(folder/'map.png'),planning_mask='mask.png',points=[[120,100]],segments=[dict(kind='walk',points=[[120,100]])])
            (folder/'planned-route.json').write_text(json.dumps(plan))
            args=SimpleNamespace(config=folder/'config.json',fast_track=True,live_route=True,planned_route=folder/'planned-route.json',
                motion_calibration=None,camera_calibration=None,forward_speed=28.5,stop_distance=6,window_title='hololive-dreams',
                window_handle=None,start_delay=0,output=folder/'run',route=folder/'missing-route.json',duration=.35,fps=30,stop_file=None)
            tracker=SimpleNamespace(reference=reference,timing={},spec=SimpleNamespace(crop=lambda *a,**kw:(np.zeros((164,164,3),np.uint8),np.full((164,164),255,np.uint8))))
            tracker.locate=lambda image,t,**kw:Position(50,100,t)
            capture=SimpleNamespace(bounds=lambda:(0,0,1259,708),grab=lambda roi:(np.zeros((709,1259,3),np.uint8),(0,0,1259,708)),close=lambda:None)
            backend=SimpleNamespace(windows=lambda:[dict(title='hololive-dreams',handle=1)])
            computer=SimpleNamespace(live=True,keys=set(),buttons=set(),close=lambda:None)
            decisions=[]
            def execute(d,**kw):decisions.append(d);return True
            with patch('modular_agent.realtime.patrol.make_vision',return_value=(None,None,None)), \
                 patch('modular_agent.domains.hololive_dreams.minimap_tracking.FastMinimapTracker',return_value=tracker), \
                 patch('modular_agent.computer.windows.WindowsBackend',return_value=backend), \
                 patch('modular_agent.realtime.keyboard.GuardedCapture',return_value=capture), \
                 patch('modular_agent.realtime.minimap_preview.MapPreview') as viewer, \
                 patch('modular_agent.computer.controller.ActionComputer',return_value=computer), \
                 patch('modular_agent.realtime.route_experience.ManualSpaceMonitor',return_value=SimpleNamespace(take_before=lambda t:[],close=lambda:None)), \
                 patch('modular_agent.realtime.route_scene.RouteSceneGate') as gate, \
                 patch('modular_agent.domains.hololive_dreams.camera_navigation.VisualCameraHeading') as sensor, \
                 patch('modular_agent.realtime.camera_navigation.camera_calibration',return_value=(folder/'camera.json',dict(degrees_per_count=.071,protocol=dict(window_bounds=[0,0,1259,708])))), \
                 patch('modular_agent.realtime.camera_navigation.ContinuousRouteExecutor',return_value=SimpleNamespace(execute=execute,prepare=lambda d,**kw:d,pause=lambda:None)):
                gate.return_value.read.return_value=(True,1.)
                sensor.return_value.read.side_effect=lambda patch,pos,t:CameraHeading(0,t,True)
                viewer.return_value.show.return_value=True
                preview(args,config)
            self.assertTrue(decisions)
            self.assertTrue(all(d.keys==('w',) for d in decisions))
            summary=json.loads((args.output/'summary.json').read_text())
            self.assertEqual(summary['control_mode'],'w_camera')

    def computer(self):
        c=SimpleNamespace(live=True,stopped=False,keys=set(),buttons=set(),events=[])
        def perform(action):
            c.events.append(action)
            if action.name=='key_down':c.keys.add(action.arguments['key'])
            return SimpleNamespace(outcome=Outcome.SUCCESS)
        c.perform=perform;c.release_all=lambda:c.keys.clear()
        return c

    def test_actual_adapter_rejects_asd_and_pickup(self):
        c=self.computer();executor=GuardedCameraExecutor(c,lambda:None)
        for key in ('a','s','d','e'):
            with self.assertRaises(ValueError):executor.execute(Decision('move','test',(key,),.1),observed_at=0)
        self.assertFalse(c.events)

    def test_cancel_during_turn_stops_remaining_mouse_input(self):
        c=self.computer();clock=[0.]
        def check():
            if clock[0]>.025:raise RuntimeError('cancelled')
        executor=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        with self.assertRaises(RuntimeError):executor.execute(CameraTurn(mouse_dx=48),observed_at=0)
        self.assertLess(sum(a.arguments['dx'] for a in c.events),48);self.assertFalse(c.keys)

    def test_delayed_popup_during_w_releases_key(self):
        c=self.computer();clock=[0.]
        def check():
            if clock[0]>.02:raise RuntimeError('popup_or_disabled')
        executor=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        with self.assertRaises(RuntimeError):executor.execute(Decision('move','test',('w',),.1),observed_at=0)
        self.assertFalse(c.keys)


if __name__=='__main__':unittest.main()
