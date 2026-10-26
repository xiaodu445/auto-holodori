import unittest
import numpy as np
import torch
from train import targets,losses,decode,PointNet


class TrainingTests(unittest.TestCase):
    def test_offsets_ignore_mask_and_collision(self):
        heat,off,pos,valid=targets([[0,10.5,13.25]],[[20,20,28,28]],2,32,32)
        self.assertEqual(heat[0,3,2],1)
        np.testing.assert_allclose(off[:,3,2],[.625,.3125])
        self.assertEqual(valid[0,5,5],0)
        with self.assertRaises(ValueError):targets([[0,10,10],[1,11,11]],[],2,32,32)

    def test_loss_ignores_unknown_area(self):
        h,o,p,v=targets([[0,10,10]],[[20,20,28,28]],1,32,32)
        h,o,p,v=[torch.from_numpy(a)[None] for a in [h,o,p,v]]
        a=torch.zeros_like(h);b=a.clone();b[:,:,5:7,5:7]=20
        self.assertAlmostEqual(losses(a,o,h,o,p,v)[0].item(),losses(b,o,h,o,p,v)[0].item())

    def test_decode_recovers_offset_and_class(self):
        h=torch.full((2,8,8),-20.);h[1,3,2]=10
        offset=torch.zeros(2,8,8);offset[:,3,2]=torch.tensor([.625,.3125])
        p=decode(h,offset)
        self.assertEqual(len(p),1);self.assertEqual(p[0]['class_index'],1)
        self.assertAlmostEqual(p[0]['x'],10.5);self.assertAlmostEqual(p[0]['y'],13.25)

    def test_network_stride_four(self):
        net=PointNet(3).eval()
        with torch.no_grad():h,o=net(torch.zeros(1,3,64,96))
        self.assertEqual(h.shape,(1,3,16,24));self.assertEqual(o.shape,(1,2,16,24))
