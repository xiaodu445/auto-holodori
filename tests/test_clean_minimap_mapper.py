import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.domains.hololive_dreams.clean_minimap_mapper import CleanMinimapMapper
from modular_agent.domains.hololive_dreams.minimap_mapper import MapperSettings,register_pixels
from modular_agent.domains.hololive_dreams.patrol_vision import read_image
from modular_agent.realtime.patrol import DATA


class CleanMapperTests(unittest.TestCase):
    def test_real_narrow_feature_seed_does_not_lock_all_following_frames(self):
        mapper=CleanMinimapMapper(MapperSettings(terrain_radius=.89))
        folder=DATA/'mapper-regression-m011'
        for n in (1,2):
            image=read_image(folder/f'frame-{n:06d}.png')
            result=mapper.add_tile(image,np.full(image.shape[:2],255,np.uint8),n*.25)
            self.assertTrue(result.accepted,result)
        self.assertEqual(result.method,'masked_pixels')
        self.assertAlmostEqual(result.x,0,delta=.2);self.assertAlmostEqual(result.y,0,delta=.2)

    def test_pixel_fallback_rejects_repeating_and_blank_ground(self):
        yy,xx=np.mgrid[:164,:164]
        image=np.repeat((((xx//4+yy//4)%2)*150+50).astype(np.uint8)[:,:,None],3,axis=2)
        mask=np.full((164,164),255,np.uint8)
        self.assertIsNone(register_pixels(image,image,mask,mask,MapperSettings()))
        image[:]=150
        self.assertIsNone(register_pixels(image,image,mask,mask,MapperSettings()))

    def test_pixel_fallback_moves_with_terrain_not_screen_mask(self):
        import cv2
        rng=np.random.default_rng(117)
        world=cv2.GaussianBlur(rng.integers(10,230,(220,220,3),np.uint8),(7,7),0)
        first=world[10:174,10:174];second=world[17:181,19:183]
        mask=np.full((164,164),255,np.uint8);mask[30:130,60:164]=0
        result=register_pixels(first,second,mask,mask,MapperSettings())
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result['dx'],9,delta=.2);self.assertAlmostEqual(result['dy'],7,delta=.2)

    def test_unknown_cone_and_unknown_scene_never_write_terrain(self):
        mapper = CleanMinimapMapper();image = np.full((164,164,3),150,np.uint8);mask = np.full((164,164),255,np.uint8)
        self.assertFalse(mapper.add_tile(image,mask,0).accepted)
        self.assertEqual(mapper.last_result.reason,'cone_direction_unknown_no_write')
        self.assertIsNone(mapper.image)
        self.assertEqual(mapper.add_tile(image,mask,1,scene_valid=False).reason,'scene_not_confirmed')

    def test_cone_exclusion_reaches_registration_composition_and_resume(self):
        mapper = CleanMinimapMapper();rng = np.random.default_rng(53)
        image = rng.integers(20,200,(164,164,3),np.uint8)
        mask = np.full((164,164),255,np.uint8);mask[:,82:] = 0
        with patch('modular_agent.domains.hololive_dreams.clean_minimap_mapper.exclude_view_cone',return_value=(mask,dict(valid=True))),patch(
            'modular_agent.domains.hololive_dreams.clean_minimap_mapper.exclude_random_markers',return_value=(mask,0)):
            self.assertTrue(mapper.add_tile(image,np.full_like(mask,255),0).accepted)
        self.assertFalse(mapper.weights[:,82:].any());self.assertFalse(mapper.previous_mask[:,82:].any())
        with tempfile.TemporaryDirectory() as folder:
            report = mapper.save(folder);self.assertIn('cone',report['overlay_policy'])
            resumed = CleanMinimapMapper.resume(Path(folder))
            self.assertEqual(resumed.accepted,1);np.testing.assert_array_equal(resumed.image,mapper.image)


if __name__=='__main__':unittest.main()
