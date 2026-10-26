"""Process-local mask loss extension; never edits the Ultralytics installation."""
import torch
import torch.nn.functional as F
import os
from pathlib import Path
os.environ.setdefault('YOLO_CONFIG_DIR',str(Path(__file__).resolve().parent/'.ultralytics'))


def erosion(x):
    return torch.minimum(-F.max_pool2d(-x,(3,1),1,(1,0)),-F.max_pool2d(-x,(1,3),1,(0,1)))


def skeleton(x,iterations=3):
    opened=F.max_pool2d(erosion(x),3,1,1)
    skel=F.relu(x-opened)
    for _ in range(iterations):
        x=erosion(x);delta=F.relu(x-F.max_pool2d(erosion(x),3,1,1))
        skel=skel+F.relu(delta-skel*delta)
    return skel


def penalties(prob,target):
    dims=(1,2,3);eps=1e-5
    dice=1-(2*(prob*target).sum(dims)+eps)/(prob.sum(dims)+target.sum(dims)+eps)
    sp=skeleton(prob);st=skeleton(target)
    precision=((sp*target).sum(dims)+eps)/(sp.sum(dims)+eps)
    sensitivity=((st*prob).sum(dims)+eps)/(st.sum(dims)+eps)
    cldice=1-2*precision*sensitivity/(precision+sensitivity+eps)
    return dice,cldice


def install():
    from ultralytics.utils.loss import v8SegmentationLoss
    from ultralytics.utils.ops import crop_mask
    original=v8SegmentationLoss.single_mask_loss
    if getattr(original,'rope_extension',False):return
    def single(gt,pred,proto,xyxy,area):
        base=original(gt,pred,proto,xyxy,area)
        # Keep standard BCE on every positive anchor; cap auxiliaries to four anchors per image.
        n=pred.shape[0];idx=torch.linspace(0,n-1,min(n,4),device=pred.device).long()
        with torch.autocast(device_type=proto.device.type,enabled=False):
            logits=torch.einsum('in,nhw->ihw',pred[idx].float(),proto.float())
            probability=crop_mask(logits.sigmoid().clone(),xyxy[idx]).unsqueeze(1)
            target=crop_mask(gt[idx].float(),xyxy[idx]).unsqueeze(1)
            dice,cldice=penalties(probability,target)
            extra=(.15*dice+.10*cldice).mean()*n
        return base+extra
    single.rope_extension=True
    v8SegmentationLoss.single_mask_loss=staticmethod(single)
