import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.anchored_mapping import AnchoredMapper, crop_padded, verify_reference
from modular_agent.domains.hololive_dreams.patrol import Position
from modular_agent.domains.hololive_dreams.patrol_vision import write_image, covered_match_scores


class AnchoredTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = np.random.default_rng(5).integers(0,255,(240,240,3),np.uint8)
        self.coverage = np.full((240,240),255,np.uint8);self.coverage[100:120,140:160] = 0
        write_image(self.root/'map.png',self.reference);write_image(self.root/'coverage.png',self.coverage)
        (self.root/'config.json').write_text(json.dumps(dict(reference='map.png',coverage='coverage.png')))
        self.mapper = AnchoredMapper(self.root/'config.json')
        self.tile = self.reference[38:202,38:202].copy();self.mask = np.full((164,164),255,np.uint8)
        self.match = dict(dx=0.,dy=0.,score=.99,inliers=30,overlap=.9,method='features')

    def accepted(self,t=0):
        with patch.object(self.mapper.locator,'match_patch',return_value=Position(120,120,t,True)),patch(
            'modular_agent.domains.hololive_dreams.anchored_mapping.verify_reference',return_value=self.match):
            return self.mapper.add_tile(self.tile,self.mask,t)

    def test_reference_never_changes_or_becomes_candidate_evidence(self):
        self.assertTrue(self.accepted().accepted)
        known = self.coverage>0
        np.testing.assert_array_equal(self.mapper.image[known],self.reference[known])
        np.testing.assert_array_equal(self.mapper.locator.reference,self.reference)
        self.assertFalse(np.any(self.mapper.locator.reference_mask[~known]))
        self.assertGreater(np.count_nonzero(self.mapper.support),0)
        self.mapper.save(self.root/'out')
        self.assertTrue((self.root/'out/candidate-overlay.png').exists())
        self.assertFalse((self.root/'out/map.png').exists())

    def test_unknown_scene_and_stale_timestamp_do_not_write(self):
        with patch.object(self.mapper.locator,'match_patch') as locate:
            self.assertFalse(self.mapper.add_tile(self.tile,self.mask,0,scene_valid=False).accepted)
            locate.assert_not_called()
        self.assertEqual(self.mapper.add_tile(self.tile,self.mask,0).reason,'stale_frame')
        self.assertFalse(self.mapper.support.any())

    def test_geometry_failure_does_not_write_despite_template_match(self):
        with patch.object(self.mapper.locator,'match_patch',return_value=Position(120,120,0,True)),patch(
            'modular_agent.domains.hololive_dreams.anchored_mapping.verify_reference',return_value=None):
            self.assertFalse(self.mapper.add_tile(self.tile,self.mask,0).accepted)
        self.assertFalse(self.mapper.support.any())

    def test_stationary_frames_do_not_increase_support(self):
        self.accepted();before = self.mapper.support.copy();self.accepted(1)
        np.testing.assert_array_equal(before,self.mapper.support)

    def test_padded_crop(self):
        tile,corner = crop_padded(self.reference,(0,0),164)
        np.testing.assert_array_equal(corner,[-82,-82])
        self.assertFalse(tile[:82].any())
        np.testing.assert_array_equal(tile[82:,82:],self.reference[:82,:82])

    def test_real_pixel_validator_rejects_unrelated_and_flat_images(self):
        reference = cv2.GaussianBlur(self.tile,(5,5),0)
        self.assertIsNotNone(verify_reference(reference,reference,self.mask,self.mask))
        unrelated = np.random.default_rng(43).integers(0,255,reference.shape,np.uint8)
        self.assertIsNone(verify_reference(reference,unrelated,self.mask,self.mask))
        flat = np.full_like(reference,100)
        self.assertIsNone(verify_reference(flat,flat,self.mask,self.mask))

    def test_single_icon_cannot_validate_entire_reference(self):
        mask = np.zeros_like(self.mask);mask[:82,:82] = 255
        self.assertIsNone(verify_reference(self.tile,self.tile,mask,mask))

    def test_unknown_holes_do_not_lower_score_or_change_best_position(self):
        rng = np.random.default_rng(52)
        reference = rng.uniform(30,220,(70,80,3)).astype(np.float32)
        template = reference[20:50,25:55].copy()
        coverage = np.full((70,80),255,np.uint8)
        coverage[22:46,30:42] = 0
        first = reference.copy();first[coverage==0] = 0
        second = reference.copy();second[coverage==0] = 255
        mask = np.full((30,30),255,np.uint8)
        scores = covered_match_scores(first,template,mask,coverage)
        other = covered_match_scores(second,template,mask,coverage)
        np.testing.assert_allclose(scores,other,atol=1e-5)
        self.assertEqual(np.unravel_index(np.argmax(scores),scores.shape),(20,25))
        self.assertGreater(scores[20,25],.999)

    def test_insufficient_coverage_cannot_create_a_high_score(self):
        coverage = np.zeros((164,164),np.uint8);coverage[:30] = 255
        scores = covered_match_scores(self.tile.astype(np.float32),self.tile.astype(np.float32),self.mask,coverage)
        self.assertEqual(float(scores[0,0]),-1)


if __name__=='__main__':unittest.main()
