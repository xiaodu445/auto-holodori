import unittest
import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_cleanup import exclude_view_cone, exclude_random_markers
from modular_agent.domains.hololive_dreams.repair_mapping import optimize_translations
from modular_agent.domains.hololive_dreams.repair_mapping import RepairMapper, consensus_colors, match_near_prior
from modular_agent.domains.hololive_dreams.minimap_mapper import MapperSettings


class ConeTests(unittest.TestCase):
    def pointer(self,heading):
        # Pale yellow terrain must not be interpreted as the pointer outline.
        image = np.full((164,164,3),(217,246,255),np.uint8)
        cv2.circle(image,(82,82),12,(255,255,255),3)
        angle = np.deg2rad(heading)
        p = np.array([[15,-5],[24,0],[15,5]],float)
        rotation = np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
        points = np.rint(p@rotation.T+82).astype(np.int32)
        cv2.polylines(image,[points],True,(255,255,255),2)
        return image

    def test_cone_rotates_and_preserves_opposite_terrain(self):
        for angle in (0,45,90,180,270):
            mask,info = exclude_view_cone(self.pointer(angle),np.full((164,164),255,np.uint8))
            self.assertTrue(info['valid'])
            error = abs((info['heading_degrees']-angle+180)%360-180)
            self.assertLess(error,8)
            a = np.deg2rad(angle);x,y = np.rint([82+55*np.cos(a),82+55*np.sin(a)]).astype(int)
            self.assertEqual(mask[y,x],0)
            self.assertEqual(mask[164-y,164-x],255)

    def test_yellow_terrain_and_missing_pointer_fail_closed(self):
        image = np.full((164,164,3),(217,246,255),np.uint8)
        mask,info = exclude_view_cone(image,np.full((164,164),255,np.uint8))
        self.assertFalse(info['valid']);self.assertFalse(mask.any())

    def test_ambiguous_opposite_pointers_fail_closed(self):
        a,b = self.pointer(0),self.pointer(180)
        image = np.maximum(a,b)
        _,info = exclude_view_cone(image,np.full((164,164),255,np.uint8))
        self.assertFalse(info['valid'])

    def test_manual_exclusions_remain_excluded(self):
        original = np.full((164,164),255,np.uint8);original[50:70,30:50] = 0
        result,_ = exclude_view_cone(self.pointer(0),original)
        self.assertFalse(result[original==0].any())

    def test_random_badges_excluded_but_broad_terrain_retained(self):
        image = np.full((164,164,3),150,np.uint8)
        cv2.rectangle(image,(90,20),(140,60),(30,220,30),-1)
        cv2.circle(image,(40,50),7,(255,255,255),-1)
        cv2.circle(image,(40,50),5,(160,0,255),-1)
        mask,count = exclude_random_markers(image,np.full((164,164),255,np.uint8))
        self.assertEqual(count,1);self.assertEqual(mask[50,40],0)
        self.assertEqual(mask[40,110],255)


class PoseTests(unittest.TestCase):
    def test_consensus_rejects_one_warm_ring_without_blending(self):
        clean = np.full((20,20,3),(100,140,160),np.uint8)
        ring = clean.copy();cv2.circle(ring,(10,10),6,(130,200,250),2)
        samples = np.stack([clean,clean,ring]);valid = np.ones((3,20,20),bool)
        result,confirmed = consensus_colors(samples,valid,ring)
        np.testing.assert_array_equal(result,clean)
        self.assertTrue(confirmed.all())

    def test_consensus_uses_real_colors_and_respects_validity(self):
        samples = np.array([[[[0,0,0]]],[[[100,120,140]]],[[[110,130,150]]],[[[105,125,145]]]],np.uint8)
        valid = np.array([[[False]],[[True]],[[True]],[[True]]])
        result,_ = consensus_colors(samples,valid,np.zeros((1,1,3),np.uint8))
        self.assertTrue(any(np.array_equal(result[0,0],s[0,0]) for s in samples[1:]))
        np.testing.assert_array_equal(result[0,0],[105,125,145])

    def test_pixel_fallback_matches_translation_but_rejects_flat(self):
        rng = np.random.default_rng(64)
        world = cv2.resize(rng.integers(20,220,(40,50,3),np.uint8),(200,200))
        previous,current = world[10:174,10:174],world[14:178,17:181]
        mask = np.full((164,164),255,np.uint8)
        match = match_near_prior(previous,current,mask,mask,(5,2))
        self.assertIsNotNone(match)
        self.assertEqual((match['dx'],match['dy']),(7,4))
        self.assertIsNone(match_near_prior(np.full_like(previous,150),np.full_like(previous,150),mask,mask,(0,0)))

    def test_wrong_manual_join_can_move_without_moving_gauge(self):
        base = np.array([[0.,0.],[12.,0.],[24.,0.]])
        edges = [(0,1,np.array([10.,0.]),4.),(1,2,np.array([10.,0.]),4.),(0,2,np.array([20.,0.]),4.)]
        solved,residuals = optimize_translations(base,edges,3)
        self.assertLess(np.linalg.norm(solved[0]),.001)
        self.assertLess(abs(solved[2,0]-20),.2)
        self.assertLess(max(residuals),.2)

    def test_isolated_manual_layers_keep_initial_positions(self):
        base = np.array([[0.,0.],[200.,100.]])
        result,_ = optimize_translations(base,[],2)
        np.testing.assert_array_equal(result,base)

    def test_rebuild_removes_old_placement_instead_of_accumulating_ghost(self):
        mapper = object.__new__(RepairMapper)
        mapper.fixed_mask = np.zeros((240,300),bool)
        mapper.fixed = np.zeros((240,300,3),np.uint8)
        mapper.settings = MapperSettings()
        image = np.full((164,164,3),170,np.uint8)
        mask = np.zeros((164,164),np.uint8);mask[60:100,60:100] = 255
        mapper.nodes = [dict(image=image,mask=mask,pose=np.array([100.,100.]))]
        mapper._render()
        self.assertTrue(mapper.weights[80:118,80:118].any())
        mapper.nodes[0]['pose'] = np.array([180.,100.])
        mapper._render()
        self.assertFalse(mapper.weights[80:118,80:118].any())
        self.assertTrue(mapper.weights[80:118,160:198].any())

    def test_masked_cone_pixels_never_enter_composite(self):
        mapper = object.__new__(RepairMapper)
        mapper.fixed_mask = np.zeros((240,240),bool);mapper.fixed = np.zeros((240,240,3),np.uint8)
        mapper.settings = MapperSettings()
        image = ConeTests().pointer(0)
        mask,info = exclude_view_cone(image,np.full((164,164),255,np.uint8))
        mapper.nodes = [dict(image=image,mask=mask,pose=np.array([120.,120.]))]
        mapper._render()
        self.assertEqual(mapper.weights[120,170],0)
        self.assertEqual(mapper.weights[120,70],1)


if __name__=='__main__':unittest.main()
