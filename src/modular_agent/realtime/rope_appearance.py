"""Rope appearance evidence, computed before and independently of template lookup."""
import cv2
import numpy as np

def rope_appearance_mask(image):
    b,g,r=np.moveaxis(image.astype(np.float32),2,0)
    # Pale ropes and their blue outline; green foliage/brown fence are excluded.
    pale=(np.minimum(np.minimum(b,g),r)>=150)&(np.maximum(np.maximum(b,g),r)-np.minimum(np.minimum(b,g),r)<=85)
    blue=(b>=r+18)&(b>=g+6)&(b>=70)
    return np.uint8(pale|blue)*255

def rope_evidence(legacy,vision,gray,indices,image):
    mask=rope_appearance_mask(image)
    inside=vision.in_bounds
    options=vision.options[indices];normals=vision.normals[indices]
    center=vision.sample(gray,options);bright=np.zeros(center.shape);thin=np.zeros(center.shape)
    for radius in (3,6):
        plus=vision.sample(gray,options+normals[:,:,None,:]*radius)
        minus=vision.sample(gray,options-normals[:,:,None,:]*radius)
        a=center-plus;b=center-minus
        bright=np.maximum(bright,np.minimum(a,b))
        thin=np.maximum(thin,np.where(a*b>0,np.minimum(abs(a),abs(b)),0))
    blue_mask=np.uint8((image[:,:,0].astype(float)>=image[:,:,2].astype(float)+18)&(image[:,:,0].astype(float)>=image[:,:,1].astype(float)+6)&(image[:,:,0]>=70))*255
    dark_blue=vision.sample(blue_mask,options)>=128
    supported=(vision.sample(mask,options)>=128)&(thin>=8)&((bright>=8)|dark_blue)
    limited=inside.copy();limited[indices]&=supported
    vision.in_bounds=limited
    try:q,raw,seen,coverage,moving=legacy._evidence(vision,gray,indices)
    finally:vision.in_bounds=inside
    # Isolated color/edge coincidences do not form a visible rope segment.
    adjacent=(seen[:,1:]&seen[:,:-1]).sum(axis=1)
    coherent=adjacent/np.maximum(1,seen.sum(axis=1)-1)
    q=np.where(coherent>=.60,q,0.)
    return q,raw,seen,coverage,moving
