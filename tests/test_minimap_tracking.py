import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_tracking import FastMinimapTracker
from modular_agent.domains.hololive_dreams.patrol_vision import write_image
from modular_agent.realtime.patrol import latest_repaired_config
from modular_agent.domains.hololive_dreams.minimap_mapper import MinimapMapper


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rng = np.random.default_rng(46)
        self.world = cv2.resize(rng.integers(30,200,(40,45,3),np.uint8),(360,320))
        write_image(self.root/'repair-map.png',self.world)
        write_image(self.root/'coverage.png',np.full(self.world.shape[:2],255,np.uint8))
        (self.root/'config.json').write_text(json.dumps(dict(reference='repair-map.png',coverage='coverage.png')))
        self.tracker = FastMinimapTracker(self.root/'config.json')
        self.tile = self.world[68:232,98:262].copy()
        self.mask = np.full((164,164),255,np.uint8)

    def test_unknown_cone_does_not_veto_two_frame_location(self):
        with patch('modular_agent.domains.hololive_dreams.minimap_tracking.exclude_view_cone',
                   return_value=(np.zeros_like(self.mask),dict(valid=False))):
            self.assertFalse(self.tracker.match_patch(self.tile,self.mask,0).valid)
            result = self.tracker.match_patch(self.tile,self.mask,.1)
        self.assertTrue(result.valid,result)
        self.assertAlmostEqual(result.x,180,delta=2)
        self.assertAlmostEqual(result.y,150,delta=2)
        self.assertFalse(self.tracker.timing['cone_known'])
        self.assertGreaterEqual(self.tracker.timing['tracking_ms'],0)

    def test_unknown_scene_resets_confirmation_and_timestamp_is_fresh(self):
        result = self.tracker.match_patch(self.tile,self.mask,0,scene_valid=False)
        self.assertEqual(result.reason,'scene_not_confirmed')
        self.assertEqual(self.tracker.match_patch(self.tile,self.mask,0).reason,'nonfresh_timestamp')
        self.assertFalse(self.tracker.match_patch(self.tile,self.mask,.1).valid)
        self.assertTrue(self.tracker.match_patch(self.tile,self.mask,.2).valid)

    def test_reference_is_read_only_and_blank_is_not_valid(self):
        before = self.tracker.reference.copy()
        blank = np.full_like(self.tile,150)
        self.assertFalse(self.tracker.match_patch(blank,self.mask,0).valid)
        np.testing.assert_array_equal(before,self.tracker.reference)

    def test_duplicate_geometry_stays_ambiguous(self):
        world = np.full((620,620,3),150,np.uint8)
        world[68:232,98:262] = self.tile
        world[368:532,398:562] = self.tile
        write_image(self.root/'repair-map.png',world)
        write_image(self.root/'coverage.png',np.full(world.shape[:2],255,np.uint8))
        tracker = FastMinimapTracker(self.root/'config.json')
        result = tracker.match_patch(self.tile,self.mask,0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason,'ambiguous_location')

    def test_latest_map_selection_ignores_incomplete_and_other_modes(self):
        for name,reference in [('20260101','repair-map.png'),('20260102','map.png'),('20260103','repair-map.png')]:
            folder = self.root/name;folder.mkdir()
            (folder/'patrol-config.json').write_text(json.dumps(dict(reference=reference)))
            if name!='20260103':write_image(folder/reference,self.world)
        self.assertEqual(latest_repaired_config(self.root).parent.name,'20260101')

    def test_preview_marker_uses_current_fix_not_last_keyframe(self):
        mapper = MinimapMapper()
        mapper.image = np.zeros((100,100,3),np.uint8);mapper.weights = np.ones((100,100),np.uint16)
        mapper.position = np.array([70.,70.]);mapper.trajectory = [dict(x=20.,y=20.,t=0)]
        canvas = mapper.display()
        self.assertEqual(tuple(canvas[70,70]),(0,0,255))
        self.assertEqual(tuple(canvas[20,20]),(0,0,0))


if __name__=='__main__':unittest.main()
