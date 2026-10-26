import unittest,numpy as np
from modular_agent.realtime.rope_appearance import rope_appearance_mask,rope_evidence
class RopeAppearanceTests(unittest.TestCase):
 def test_pale_and_blue_rope_reject_foliage_fence(self):
  a=np.array([[[230,220,215],[130,110,70],[80,150,100],[120,150,175],[195,205,250]]],np.uint8)
  self.assertEqual(rope_appearance_mask(a).tolist(),[[255,255,0,0,255]])
 def test_restriction_restored_even_on_failure(self):
  class Vision:
   normals=np.zeros((1,41,2));options=np.zeros((1,41,3,2));in_bounds=np.ones((1,41,3),bool)
   def sample(self,image,points):return np.zeros(points.shape[:-1])
  class Legacy:
   def _evidence(self,v,g,i):
    assert not v.in_bounds.any()
    raise RuntimeError('expected')
  v=Vision();original=v.in_bounds
  with self.assertRaises(RuntimeError):rope_evidence(Legacy(),v,np.zeros((4,4)),np.array([0]),np.zeros((4,4,3),np.uint8))
  self.assertIs(v.in_bounds,original)
 def test_scattered_points_are_not_a_rope(self):
  class Vision:
   normals=np.zeros((1,41,2));options=np.zeros((1,41,3,2));in_bounds=np.ones((1,41,3),bool)
   def sample(self,image,points):return np.full(points.shape[:-1],255)
  class Legacy:
   def _evidence(self,v,g,i):
    seen=np.zeros((1,41),bool);seen[:,::2]=True
    return np.array([.9]),np.zeros((1,41,2)),seen,np.array([.5]),np.array([.5])
  q,*_=rope_evidence(Legacy(),Vision(),np.zeros((4,4)),np.array([0]),np.zeros((4,4,3),np.uint8));self.assertEqual(q[0],0)
 def test_lighting_and_dark_background_ridge(self):
  import cv2
  class Vision:
   normals=np.tile([0.,1.],(1,41,1));options=np.array([[[[x,20.]] for x in range(10,51)]],float);in_bounds=np.ones((1,41,1),bool)
   def sample(self,im,points):
    xy=np.rint(points).astype(int);return im[np.clip(xy[...,1],0,39),np.clip(xy[...,0],0,59)].astype(float)
  class Legacy:
   def _evidence(self,v,g,i):
    seen=v.in_bounds[:,:,0];q=seen.mean(axis=1)
    return q,np.zeros((1,41,2)),seen,q,q
  for color,bg,expected in [([190,210,245],80,1),([180,180,180],230,0),([100,75,45],180,1)]:
   im=np.full((40,60,3),bg,np.uint8);im[20,10:51]=color
   q,*_=rope_evidence(Legacy(),Vision(),cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),np.array([0]),im);self.assertEqual(q[0],expected)
