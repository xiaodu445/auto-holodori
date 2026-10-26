from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import (
    MinimapMapper,MapperSettings,FrontierExplorer,register_tiles,
)
from modular_agent.domains.hololive_dreams.patrol import MotionCalibration
from modular_agent.domains.hololive_dreams.patrol_vision import MinimapLocalizer,MinimapSpec,read_image
from modular_agent.realtime.minimap_scan import FreeWorldGate,ProbeCalibration
from modular_agent.realtime.patrol import DATA,make_vision


class MappingFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        rng = np.random.default_rng(83)
        cls.world = cv2.resize(rng.integers(20,230,(70,90,3),dtype=np.uint8),(720,560),interpolation=cv2.INTER_NEAREST)
        yy,xx = np.ogrid[:164,:164]
        rr = ((xx-82)**2+(yy-82)**2)/82**2
        cls.mask = ((rr<.94**2)&(rr>.28**2)).astype(np.uint8)*255

    def patch(self,x,y):
        return self.world[y-82:y+82,x-82:x+82].copy()

    def seed(self,**settings):
        mapper = MinimapMapper(MapperSettings(**settings))
        r = mapper.add_tile(self.patch(200,200),self.mask,0)
        self.assertTrue(r.accepted)
        return mapper


class MappingTests(MappingFixture):
    def test_warm_scanning_overlay_is_not_baked_into_map(self):
        # The moving HUD overlay warms the same terrain pixel. It must not
        # become a permanent circular stain, regardless of arrival order.
        base = np.full((164,164,3),(170,185,175),np.uint8)
        overlay = np.rint(base.astype(float)*.5+np.array((160,232,255))*.5).astype(np.uint8)
        for first,second in ((base,overlay),(overlay,base)):
            mapper = MinimapMapper()
            mapper._integrate(first,self.mask,(0,0))
            mapper._integrate(second,self.mask,(0,0))
            np.testing.assert_array_equal(mapper.image[self.mask>0],base[self.mask>0])

    def test_real_hud_ring_is_excluded(self):
        fixture = DATA/'mapper-regression-20261025/frame-000001.png'
        image = read_image(fixture)
        mapper = MinimapMapper()
        self.assertTrue(mapper.add_tile(image,np.full((164,164),255,np.uint8),0).accepted)
        hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        red = ((hsv[:,:,0]<12)|(hsv[:,:,0]>170))&(hsv[:,:,1]>80)&(hsv[:,:,2]>100)
        self.assertGreater(np.count_nonzero(red),0)
        self.assertEqual(np.count_nonzero(red&(mapper.weights>0)),0)


    def test_tracks_positive_negative_and_returns_to_origin(self):
        m = self.seed()
        for t,x,y in ((1,212,200),(2,224,208),(3,216,216),(4,200,200)):
            result = m.add_tile(self.patch(x,y),self.mask,t)
            self.assertTrue(result.accepted,result)
            self.assertAlmostEqual(result.x,x-200,delta=.5)
            self.assertAlmostEqual(result.y,y-200,delta=.5)

    def test_center_avatar_does_not_drag_the_map(self):
        m = self.seed()
        image = self.patch(200,200)
        cv2.circle(image,(82,82),20,(0,0,255),-1)
        result = m.add_tile(image,self.mask,1)
        self.assertTrue(result.accepted,result)
        self.assertAlmostEqual(result.x,0,delta=.5)
        self.assertAlmostEqual(result.y,0,delta=.5)

    def test_blank_rejected_without_mutating_canvas(self):
        m = self.seed();old = m.image.copy();pose = m.position.copy()
        r = m.add_tile(np.zeros((164,164,3),np.uint8),self.mask,1)
        self.assertFalse(r.accepted)
        np.testing.assert_array_equal(old,m.image)
        np.testing.assert_array_equal(pose,m.position)

    def test_unrelated_scene_not_pasted(self):
        m = self.seed();old = m.image.copy()
        r = m.add_tile(self.patch(500,400),self.mask,1)
        self.assertFalse(r.accepted)
        np.testing.assert_array_equal(old,m.image)

    def test_unknown_scene_inhibits_seed_and_update(self):
        m = MinimapMapper()
        self.assertFalse(m.add_tile(self.patch(200,200),self.mask,0,scene_valid=False).accepted)
        self.assertIsNone(m.image)
        self.assertTrue(m.add_tile(self.patch(200,200),self.mask,1).accepted)
        self.assertFalse(m.add_tile(self.patch(208,200),self.mask,2,scene_valid=False).accepted)
        self.assertEqual(m.tiles,1)

    def test_duplicate_and_future_nonfinite_timestamps(self):
        m = self.seed()
        for t in (0,-1,float('nan'),float('inf')):
            self.assertFalse(m.add_tile(self.patch(200,200),self.mask,t).accepted)
        self.assertEqual(m.tiles,1)

    def test_resize_rejected(self):
        m = self.seed()
        r = m.add_tile(cv2.resize(self.patch(200,200),(180,180)),np.full((180,180),255,np.uint8),1)
        self.assertEqual(r.reason,'minimap_size_changed')

    def test_rotation_and_zoom_not_silently_warped(self):
        m = self.seed();image = self.patch(200,200)
        for angle,scale in ((8,1),(0,1.15)):
            changed = cv2.warpAffine(image,cv2.getRotationMatrix2D((82,82),angle,scale),(164,164))
            result = m.add_tile(changed,self.mask,angle+scale+2)
            self.assertFalse(result.accepted,result)

    def test_missed_frame_recovery_from_last_good_tile(self):
        m = self.seed()
        m.add_tile(np.zeros((164,164,3),np.uint8),self.mask,1)
        r = m.add_tile(self.patch(212,200),self.mask,2)
        self.assertTrue(r.accepted)
        self.assertAlmostEqual(r.x,12,delta=.5)

    def test_known_pixels_expand_unknown_not_fabricated(self):
        m = self.seed()
        before = np.count_nonzero(m.weights)
        self.assertEqual(m.weights[82,82],0)
        r = m.add_tile(self.patch(224,200),self.mask,1)
        self.assertTrue(r.accepted)
        self.assertGreater(r.new_pixels,0)
        self.assertGreater(np.count_nonzero(m.weights),before)
        self.assertEqual(m.weights[0,0],0)

    def test_canvas_and_tile_budgets(self):
        m = self.seed(max_canvas_side=164)
        self.assertEqual(m.add_tile(self.patch(208,200),self.mask,1).reason,'canvas_budget')
        m = self.seed(max_tiles=1)
        self.assertEqual(m.add_tile(self.patch(208,200),self.mask,1).reason,'tile_budget')

    def test_save_resume_and_export_config(self):
        m = self.seed();m.add_tile(self.patch(212,200),self.mask,1)
        with tempfile.TemporaryDirectory() as folder:
            report = m.save(folder)
            self.assertFalse(report['entire_world_explored'])
            for name in ('map.png','map-transparent.png','coverage.png','preview.png','state.npz','mapping.json','patrol-config.json'):
                self.assertTrue((Path(folder)/name).exists(),name)
            config = json.loads((Path(folder)/'patrol-config.json').read_text())
            self.assertFalse(config['minimap']['mask_dynamic_icons'])
            reference,loc,_ = make_vision(config,Path(folder)/'patrol-config.json')
            self.assertEqual(loc.patch_size,164)
            self.assertIsNotNone(loc.reference_mask)
            resumed = MinimapMapper.resume(folder)
            self.assertTrue(resumed.add_tile(self.patch(224,200),self.mask,0).accepted)
            self.assertAlmostEqual(resumed.position[0],24,delta=.5)

    def test_registration_requires_enough_valid_overlap(self):
        mask = np.zeros_like(self.mask);mask[:4,:4] = 255
        self.assertIsNone(register_tiles(self.patch(200,200),self.patch(208,200),mask,mask))

    def test_repetitive_texture_is_not_a_unique_position(self):
        rng = np.random.default_rng(11)
        pattern = rng.integers(0,255,(16,16,3),dtype=np.uint8)
        repeated = np.tile(pattern,(11,11,1))[:164,:164]
        self.assertIsNone(register_tiles(repeated,repeated,self.mask,self.mask))

    def test_invalid_settings(self):
        for kwargs in ({'max_shift':100},{'max_tiles':0},{'tile_size':20},{'min_similarity':1.1}):
            with self.assertRaises(ValueError):
                MapperSettings(**kwargs)

    def test_coverage_mask_blocks_unknown_reference(self):
        image = self.world
        loc = MinimapLocalizer(image,scales=(1,),analysis_scale=1,stable_frames=1,
                              reference_mask=np.zeros(image.shape[:2],np.uint8))
        p = loc.match_patch(self.patch(200,200),self.mask,0)
        self.assertFalse(p.valid)
        self.assertEqual(p.reason,'insufficient_reference_coverage')


class ExplorationTests(MappingFixture):
    def motion(self):
        return MotionCalibration({'w':(0,-40),'a':(-40,0),'s':(0,40),'d':(40,0)})

    def test_explorer_requires_calibration(self):
        with self.assertRaises(ValueError):
            FrontierExplorer(MotionCalibration())

    def test_cancel_and_missing_mapping_zero_movement(self):
        explorer = FrontierExplorer(self.motion())
        self.assertEqual(explorer.propose(MinimapMapper()).kind,'wait')
        self.assertEqual(explorer.propose(MinimapMapper(),cancelled=True).kind,'stop')

    def test_only_dispatch_consumes_action_budget(self):
        m = self.seed();e = FrontierExplorer(self.motion(),max_actions=1)
        d = e.propose(m)
        self.assertEqual(d.kind,'move')
        self.assertEqual(e.actions,0)
        e.dispatched(m,d)
        self.assertEqual(e.propose(m).reason,'exploration_action_budget')

    def test_no_progress_changes_direction_then_stops(self):
        m = self.seed();e = FrontierExplorer(self.motion(),max_no_progress=4)
        keys = []
        for i in range(4):
            d = e.propose(m);keys.append(d.keys[0]);e.dispatched(m,d)
        self.assertEqual(len(set(keys)),4)
        self.assertEqual(e.propose(m).reason,'no_displacement_manual_recovery')

    def test_calibration_four_measured_pulses(self):
        m = self.seed();probe = ProbeCalibration()
        vectors = self.motion().vectors
        for i,key in enumerate('wasd'):
            d = probe.step(m,i)
            self.assertEqual(d.keys,(key,))
            probe.dispatched(m,d,i)
            m.position += np.array(vectors[key])*.3
        self.assertIsNone(probe.step(m,5))
        probe.motion.validate()

    def test_calibration_stuck_is_rejected(self):
        m = self.seed();probe = ProbeCalibration()
        d = probe.step(m,0);probe.dispatched(m,d,0)
        with self.assertRaises(ValueError):
            probe.step(m,1)

    def test_blocked_end_backtracks_recorded_route(self):
        m = self.seed()
        for i,x in enumerate(range(212,261,12),1):
            self.assertTrue(m.add_tile(self.patch(x,200),self.mask,i).accepted)
        e = FrontierExplorer(self.motion())
        cell = tuple(np.rint(m.position/12).astype(int))
        e.blocked[cell] = set('wasd')
        decision = e.propose(m)
        self.assertEqual(decision.reason,'backtrack_recorded_path_to_frontier')
        self.assertEqual(decision.keys,('a',))

    def test_no_frontier_does_not_claim_world_completion(self):
        m = self.seed()
        m.weights = np.ones((1024,1024),np.uint16);m.origin = (-512,-512)
        decision = FrontierExplorer(self.motion()).propose(m)
        self.assertEqual(decision.kind,'stop')
        self.assertIn('world_completion_unknown',decision.reason)

    def test_free_world_gate_on_supplied_images(self):
        gate = FreeWorldGate()
        for name,valid in (('free-world',True),('pickup',True),('map-partial',False)):
            frame = read_image(DATA/f'references/{name}.png')[38:,:1260]
            self.assertEqual(gate.read(frame)[0],valid,name)


class RuntimeTests(unittest.TestCase):
    def test_manual_loop_never_constructs_input_and_saves(self):
        from modular_agent.realtime.minimap_scan import run
        frame = read_image(DATA/'references/free-world.png')[38:,:1260]
        class Capture:
            def __init__(self,*args,**kwargs):
                self.closed = False
            def bounds(self):
                return (0,0,1260,709)
            def grab(self,roi):
                return frame.copy(),self.bounds()
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder);(folder/'tiles').mkdir()
            args = SimpleNamespace(window_handle=1,window_title='unused',no_preview=True,start_delay=0,
                                   auto_walk=False,auto_calibrate=False,motion_calibration=None,
                                   max_actions=5,stop_file=None,output=folder,duration=5,max_frames=2,
                                   save_interval=15,fps=20)
            with patch('modular_agent.computer.windows.WindowsBackend') as backend, \
                 patch('modular_agent.realtime.keyboard.GuardedCapture',Capture), \
                 patch('modular_agent.computer.controller.ActionComputer') as computer:
                result = run(args,MinimapMapper())
                computer.assert_not_called()
            self.assertEqual(result,0)
            session = json.loads((folder/'session.json').read_text())
            self.assertEqual(session['reason'],'frame_budget')
            self.assertEqual(session['inputs_dispatched'],0)
            self.assertTrue((folder/'map.png').exists())

    def test_auto_loop_unknown_scene_does_not_dispatch(self):
        from modular_agent.realtime.minimap_scan import run
        frame = read_image(DATA/'references/map-partial.png')[38:,:1260]
        class Capture:
            def __init__(self,*args,**kwargs):
                pass
            def bounds(self):
                return (0,0,1260,709)
            def grab(self,roi):
                return frame.copy(),self.bounds()
            def close(self):
                pass
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder);(folder/'tiles').mkdir()
            args = SimpleNamespace(window_handle=1,window_title='unused',no_preview=True,start_delay=0,
                                   auto_walk=True,auto_calibrate=True,motion_calibration=None,
                                   max_actions=5,stop_file=None,output=folder,duration=5,max_frames=2,
                                   save_interval=15,fps=20)
            with patch('modular_agent.computer.windows.WindowsBackend'), \
                 patch('modular_agent.realtime.keyboard.GuardedCapture',Capture), \
                 patch('modular_agent.computer.controller.ActionComputer') as computer:
                run(args,MinimapMapper())
                computer.return_value.perform.assert_not_called()
                computer.return_value.close.assert_called_once()
            session = json.loads((folder/'session.json').read_text())
            self.assertEqual(session['reason'],'mapping_lost_auto_stopped')
            self.assertEqual(session['inputs_dispatched'],0)


if __name__=='__main__':
    unittest.main()
