"""Configurable color candidates; components are not guaranteed object instances."""
import time
import cv2
import numpy as np


def average_hsv(image, kernel=0):
    """Saturation-weighted circular hue mean, arithmetic S/V mean."""
    if image.size==0:raise ValueError('empty color sample')
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV).astype(np.float32)
    angle=hsv[:,:,0]*(2*np.pi/180)
    weight=hsv[:,:,1]/255
    fields=np.stack([np.cos(angle)*weight,np.sin(angle)*weight,hsv[:,:,1],hsv[:,:,2]],axis=2)
    if kernel:
        if kernel<1 or kernel%2!=1:raise ValueError('average_kernel must be positive odd')
        fields=cv2.blur(fields,(kernel,kernel),borderType=cv2.BORDER_REFLECT_101)
    else:
        fields=fields.mean(axis=(0,1))
    hue=np.mod(np.arctan2(fields[...,1],fields[...,0])*(180/(2*np.pi)),180)
    return np.stack([hue,fields[...,2],fields[...,3]],axis=-1)


def detect(image, profile):
    started=time.perf_counter()
    h,w=image.shape[:2]
    l,t,r,b=profile.get('roi',[.225,.19,.78,.80])
    if not 0<=l<r<=1 or not 0<=t<b<=1:raise ValueError('invalid ROI')
    x0,y0,x1,y1=round(l*w),round(t*h),round(r*w),round(b*h)
    if x1<=x0 or y1<=y0:raise ValueError('empty ROI')
    kernel=profile.get('average_kernel',5)
    if kernel<1 or kernel%2!=1:raise ValueError('average_kernel must be positive odd')
    hsv=average_hsv(image[y0:y1,x0:x1],kernel)
    masks=[];names=[]
    for name,rule in profile.get('classes',{}).items():
        mask=np.zeros(hsv.shape[:2],np.uint8)
        for sample in rule.get('samples',[]):
            center=np.array(sample,dtype=np.float32)
            delta=np.abs(hsv-center)
            delta[:,:,0]=np.minimum(delta[:,:,0],180-delta[:,:,0])
            tolerance=rule.get('tolerance',[6,55,65])
            mask[np.all(delta<=np.array(tolerance),axis=2)]=255
        masks.append(mask);names.append(name)
    if not masks:return [],dict(elapsed_ms=(time.perf_counter()-started)*1000,ambiguous_pixels=0)
    claims=np.sum(np.stack(masks)>0,axis=0)
    results=[]
    for name,mask in zip(names,masks):
        mask[claims>1]=0
        rule=profile['classes'][name]
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        for label in range(1,n):
            x,y,cw,ch,area=map(int,stats[label])
            if area<rule.get('min_area',20):continue
            component=(labels[y:y+ch,x:x+cw]==label).astype(np.uint8)
            # Padding makes the crop border an unsafe boundary, too.
            distance=cv2.distanceTransform(np.pad(component,1),cv2.DIST_L2,5)[1:-1,1:-1]
            _,radius,_,point=cv2.minMaxLoc(distance)
            if radius<rule.get('min_radius',2):continue
            px,py=x0+x+point[0],y0+y+point[1]
            results.append(dict(class_name=name,x=px,y=py,uv=[px/w,py/h],
                color_margin_px=round(radius,2),area=area,bbox=[x0+x,y0+y,cw,ch],
                status='unverified_color_component'))
    return results,dict(elapsed_ms=(time.perf_counter()-started)*1000,
                        ambiguous_pixels=int(np.count_nonzero(claims>1)))


def overlay(image,results,roi):
    out=image.copy();h,w=out.shape[:2]
    l,t,r,b=roi
    cv2.rectangle(out,(round(l*w),round(t*h)),(round(r*w),round(b*h)),(255,180,0),2)
    for item in results:
        x,y=item['x'],item['y']
        cv2.circle(out,(x,y),5,(0,255,0),2)
        cv2.putText(out,item['class_name'],(x+7,y),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,255,0),1)
    return out
