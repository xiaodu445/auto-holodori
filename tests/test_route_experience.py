import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from modular_agent.core import Action,Outcome
from modular_agent.domains.hololive_dreams.patrol import Position
from modular_agent.domains.hololive_dreams.camera_navigation import CameraHeading,CameraWRouteFollower
from modular_agent.domains.hololive_dreams.route_experience import (
    RouteExperience,SemiInertialEstimate,Demonstration,demonstration_plan,route_key,seed_demonstration_jumps)
from modular_agent.realtime.route_experience import ManualSpaceBuffer,InputMeter


def plan():return dict(map_sha256='test-map',planning='annotation_astar',segments=[dict(kind='walk',points=[[10,10],[100,10]])],points=[[10,10],[100,10]])
def heading(t,angle=0,valid=True):return CameraHeading(angle,t,valid,'test',1)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'memory.json';self.memory=RouteExperience(plan(),self.path)

    def learn(self):
        self.memory.observe(Position(20,10,0),heading(0),1)
        self.memory.observe(Position(24,10,.2),heading(.2),1)
        return self.memory.learn(.1)

    def test_physical_jump_interpolates_and_persists_without_immediate_repeat(self):
        item=self.learn();self.assertEqual(item['xy'],[22,10]);self.assertFalse(item['landing_verified'])
        self.assertIsNone(self.memory.due(Position(22,10,.2),heading(.2),1,.2))
        next_run=RouteExperience(plan(),self.path)
        self.assertEqual(next_run.due(Position(22,10,1),heading(1),1,1)['id'],item['id'])

    def test_reverse_direction_other_segment_stale_and_missing_heading_do_not_jump(self):
        self.learn();memory=RouteExperience(plan(),self.path)
        for pos,h,index,now in ((Position(22,10,1),heading(1,180),1,1),
                (Position(22,10,1),heading(1),2,1),(Position(22,10,1),heading(1),1,2),
                (Position(22,10,1),heading(1,valid=False),1,1)):
            self.assertIsNone(memory.due(pos,h,index,now))

    def test_attempt_consumed_only_when_dispatched_no_auto_retry(self):
        self.learn();memory=RouteExperience(plan(),self.path)
        item=memory.due(Position(22,10,1),heading(1),1,1)
        self.assertIsNotNone(memory.due(Position(22,10,1.1),heading(1.1),1,1.1))
        memory.fired.add(item['id'])
        self.assertIsNone(memory.due(Position(22,10,1.2),heading(1.2),1,1.2))

    def test_bad_scene_localization_gap_and_future_event_are_not_learned(self):
        self.assertIsNone(self.memory.learn(.1))
        self.memory.observe(Position(20,10,0),heading(0),1)
        self.memory.observe(Position(24,10,.2,valid=False),heading(.2),1)
        self.assertIsNone(self.memory.learn(.1));self.assertIsNone(self.memory.learn(1))
        self.memory.observe(Position(24,10,2),heading(2),1)
        self.assertIsNone(self.memory.learn(1))
        self.assertFalse(self.path.exists())

    def test_duplicates_merge_and_other_map_or_geometry_rejected(self):
        first=self.learn();second=self.learn()
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.memory.jumps),1)
        with self.assertRaises(ValueError):RouteExperience(dict(plan(),map_sha256='another-map'),self.path)
        changed=dict(plan(),segments=[dict(kind='walk',points=[[10,10],[100,20]])])
        with self.assertRaises(ValueError):RouteExperience(changed,self.path)

    def test_remembered_space_does_not_enter_directed_jump_landing_machine(self):
        from modular_agent.domains.hololive_dreams.patrol import Decision
        f=CameraWRouteFollower(plan(),np.full((120,120),255,np.uint8),degrees_per_count=.071,continuous=True)
        f.cruising=True;f.dispatched(Decision('jump','remembered_space',('w','space'),.12),1)
        self.assertIsNone(f.jump_at);self.assertFalse(f.cruising);self.assertTrue(f.settling)

    def test_remembered_jump_dropped_space_cancel_popup_and_disabled_release(self):
        from modular_agent.domains.hololive_dreams.patrol import Decision
        from modular_agent.realtime.camera_navigation import GuardedCameraExecutor
        for failure in ('dropped_space','cancelled','delayed_popup','disabled'):
            with self.subTest(failure=failure):
                clock=[0.];events=[];c=SimpleNamespace(keys=set(),buttons=set(),live=True,stopped=False)
                def perform(action):
                    events.append(action)
                    if action.name=='key_down':
                        if action.arguments['key']=='space' and failure=='dropped_space':return SimpleNamespace(outcome='failed',message=failure)
                        c.keys.add(action.arguments['key'])
                    return SimpleNamespace(outcome=Outcome.SUCCESS)
                c.perform=perform;c.release_all=lambda:c.keys.clear()
                def check():
                    if failure=='disabled' or (failure in ('cancelled','delayed_popup') and clock[0]>.025):raise RuntimeError(failure)
                executor=GuardedCameraExecutor(c,check,clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
                with self.assertRaises(RuntimeError):executor.execute(Decision('jump','remembered_space',('w','space'),.12),observed_at=0)
                self.assertFalse(c.keys)
                self.assertLessEqual(sum(a.arguments.get('key')=='space' for a in events),1)


class InputObservationTests(unittest.TestCase):
    def test_injected_space_repeat_and_other_windows_are_filtered(self):
        b=ManualSpaceBuffer()
        b.feed(32,0x100,0x10,True,0);b.feed(32,0x101,0x10,True,.1)
        b.feed(65,0x100,0,True,.2)
        b.feed(32,0x100,0,False,.3);b.feed(32,0x101,0,False,.4)
        b.feed(32,0x100,0,True,.5);b.feed(32,0x100,0,True,.6)
        self.assertEqual(b.take_before(.55),[.5]);self.assertEqual(b.take_before(1),[])
        b.feed(32,0x101,0,True,1);b.feed(32,0x100,0,True,1.1)
        self.assertEqual(b.take_before(2),[1.1])

    def test_meter_aligns_to_capture_and_counts_only_successful_input(self):
        clock=[0.];c=SimpleNamespace(keys=set())
        def perform(a):
            if a.name=='key_down':c.keys.add(a.arguments['key'])
            if a.name=='key_up':c.keys.discard(a.arguments['key'])
            return SimpleNamespace(outcome=Outcome.SUCCESS)
        c.perform=perform;c.release_all=lambda:c.keys.clear()
        meter=InputMeter(c,clock=lambda:clock[0])
        clock[0]=.1;meter.perform(Action('key_down',arguments=dict(key='w')))
        clock[0]=.2;meter.perform(Action('move_relative',arguments=dict(dx=10,dy=0)))
        clock[0]=.3;meter.release_all()
        self.assertEqual(meter.snapshot(.15)['mouse_counts'],0)
        self.assertEqual(meter.snapshot(.25)['mouse_counts'],10)
        self.assertAlmostEqual(meter.snapshot(.25)['w_seconds'],.15)
        self.assertAlmostEqual(meter.snapshot(.5)['w_seconds'],.2)
        c.perform=lambda a:SimpleNamespace(outcome='failed')
        meter.perform(Action('move_relative',arguments=dict(dx=100,dy=0)))
        self.assertEqual(meter.snapshot(.5)['mouse_counts'],10)


class EstimatorTests(unittest.TestCase):
    def test_input_prediction_is_not_accepted_as_visual_turn_response(self):
        f=CameraWRouteFollower(plan(),np.full((120,120),255,np.uint8),degrees_per_count=.071,continuous=True)
        f.index=1;f.waypoint_index=1;f.cruising=True;f.settling=False;f.steering_check=(5,0,-30)
        d=f.step(Position(20,10,1.2),1,1.2,heading=CameraHeading(4,1.2,True,'input_prediction_bridge'))
        self.assertEqual(d.kind,'cruise');self.assertIsNotNone(f.steering_check)
        d=f.step(Position(22,10,1.4),2,1.4,heading=heading(1.4,5))
        self.assertEqual(d.reason,'camera_turn_not_observed')

    def test_semantic_policies_keep_teaching_passive_and_jump_nonrepeatable_by_menu(self):
        from modular_agent.domains.hololive_dreams.interaction import policy_for,RetryBudget
        self.assertEqual(policy_for('route_teaching').mode,'passive')
        self.assertEqual(policy_for('route_memory_jump').mode,'realtime')
        self.assertFalse(RetryBudget(policy_for('route_memory_jump')).ready(10))

    def meter(self,w,dx=0):return dict(w_seconds=w,mouse_counts=dx)

    def test_visual_snaps_fused_and_retains_free_inertial_comparison(self):
        f=SemiInertialEstimate(10,.1)
        f.update(Position(0,0,0),heading(0),self.meter(0))
        pos,h,row=f.update(Position(8,0,1),heading(1),self.meter(1),mode='fused',cruising=True)
        self.assertEqual(pos.x,8);self.assertEqual(row['prediction'],[10,0])
        self.assertEqual(row['inertial_error_pixels'],2)
        pos,h,row=f.update(Position(16,0,2),heading(2),self.meter(2))
        self.assertEqual(row['prediction'],[18,0]);self.assertEqual(row['inertial_position'],[20,0])

    def test_prediction_bridges_only_quarter_second_during_existing_cruise(self):
        for mode,cruising,valid in (('visual',True,False),('fused',False,False),('fused',True,True)):
            f=SemiInertialEstimate(10,.1);f.update(Position(0,0,0),heading(0),self.meter(0))
            pos,h,row=f.update(Position(0,0,.2,valid=False),heading(.2,valid=False),self.meter(.2),mode=mode,cruising=cruising)
            self.assertEqual(pos.valid,valid)
            pos,h,row=f.update(Position(0,0,.5,valid=False),heading(.5,valid=False),self.meter(.5),mode='fused',cruising=True)
            self.assertFalse(pos.valid)

    def test_popup_disabled_scene_never_bridged(self):
        f=SemiInertialEstimate(10,.1);f.update(Position(0,0,0),heading(0),self.meter(0))
        pos,h,row=f.update(Position(0,0,.1,valid=False),heading(.1,valid=False),self.meter(.1),mode='fused',cruising=True,scene=False)
        self.assertFalse(pos.valid);self.assertFalse(row['used_prediction'])


class DemonstrationTests(unittest.TestCase):
    def test_teaching_preview_records_without_creating_input_computer(self):
        from unittest.mock import patch
        from modular_agent.realtime.patrol import preview
        from modular_agent.domains.hololive_dreams.patrol_vision import write_image
        from modular_agent.domains.hololive_dreams.navigation_annotations import digest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=np.full((120,120,3),150,np.uint8)
            write_image(root/'map.png',image);write_image(root/'mask.png',np.full((120,120),255,np.uint8))
            config=dict(reference='map.png');(root/'config.json').write_text(json.dumps(config))
            route=dict(plan(),map_sha256=digest(root/'map.png'),planning_mask='mask.png')
            (root/'planned-route.json').write_text(json.dumps(route))
            args=SimpleNamespace(config=root/'config.json',fast_track=True,live_route=False,teach_route=True,
                planned_route=root/'planned-route.json',experience_root=root/'memory',motion_calibration=None,
                window_title='game',window_handle=None,start_delay=0,output=root/'run',duration=.3,fps=30,stop_file=None,
                route=root/'missing.json')
            tracker=SimpleNamespace(reference=image,timing={},spec=SimpleNamespace(crop=lambda *a,**k:(image,None)))
            tracker.locate=lambda image,t,**k:Position(20+t*40,10,t)
            capture=SimpleNamespace(bounds=lambda:(0,0,120,120),grab=lambda r:(image,(0,0,120,120)),close=lambda:None)
            with patch('modular_agent.realtime.patrol.make_vision',return_value=(None,None,None)), \
                 patch('modular_agent.domains.hololive_dreams.minimap_tracking.FastMinimapTracker',return_value=tracker), \
                 patch('modular_agent.computer.windows.WindowsBackend',return_value=SimpleNamespace(windows=lambda:[dict(title='game',handle=1)])), \
                 patch('modular_agent.realtime.keyboard.GuardedCapture',return_value=capture), \
                 patch('modular_agent.realtime.minimap_preview.MapPreview') as viewer, \
                 patch('modular_agent.realtime.route_scene.RouteSceneGate') as gate, \
                 patch('modular_agent.domains.hololive_dreams.camera_navigation.VisualCameraHeading') as sensor, \
                 patch('modular_agent.realtime.route_experience.ManualSpaceMonitor',return_value=SimpleNamespace(take_before=lambda t:[],close=lambda:None)), \
                 patch('modular_agent.computer.controller.ActionComputer') as computer:
                viewer.return_value.show.return_value=True;gate.return_value.read.return_value=(True,1.)
                sensor.return_value.read.side_effect=lambda image,pos,t:heading(t)
                preview(args,config);computer.assert_not_called()
            summary=json.loads((root/'run/summary.json').read_text())
            self.assertEqual(summary['control_mode'],'teaching');self.assertFalse(summary['sends_input'])
            data=json.loads(Path(summary['demonstration_file']).read_text())
            self.assertGreater(len(data['points']),2)

    def setUp(self):self.mask=np.full((120,120),255,np.uint8)
    def data(self):return dict(base_route_key=route_key(plan()),map_sha256='test-map',interrupted=False,
        points=[dict(xy=xy,t=i*.2) for i,xy in enumerate([[10,10],[40,10],[40,40]])])

    def test_preserves_manual_detour_and_does_not_shortcut(self):
        result=demonstration_plan(plan(),self.data(),self.mask)
        self.assertEqual(result['points'],[[10,10],[40,10],[40,40]])

    def test_bad_map_gap_or_blocked_path_reject_replay(self):
        for data in (dict(self.data(),map_sha256='other'),dict(self.data(),interrupted=True)):
            with self.assertRaises(ValueError):demonstration_plan(plan(),data,self.mask)
        self.mask[10,25]=0
        with self.assertRaises(ValueError):demonstration_plan(plan(),self.data(),self.mask)

    def test_incomplete_demonstration_does_not_overwrite_good_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'demo.json';path.write_text('original',encoding='utf-8')
            d=Demonstration(plan());d.observe(Position(10,10,0));d.observe(Position(0,0,.1,valid=False));d.observe(Position(20,10,.2))
            candidate=d.save(path)
            self.assertNotEqual(candidate,path);self.assertEqual(path.read_text(),'original')
            self.assertTrue(json.loads(candidate.read_text())['interrupted'])

    def test_seed_jump_rebinds_to_demonstrated_segment_direction(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=RouteExperience(plan(),Path(folder)/'memory.json')
            data=dict(jumps=[dict(id='one',xy=[22,10],heading=0,action_index=99)])
            actions=[dict(target=[10,10]),dict(target=[100,10])]
            seed_demonstration_jumps(memory,data,actions)
            self.assertEqual(memory.jumps[0]['action_index'],1)


if __name__=='__main__':unittest.main()
