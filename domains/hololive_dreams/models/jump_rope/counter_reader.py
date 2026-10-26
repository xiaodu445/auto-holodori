"""Local jump-counter glyphs; complete three-digit ROI and reference variants."""
import cv2
import numpy as np


def counter_glyphs(image):
    h,w=image.shape[:2]
    crop=image[round(.055*h):round(.225*h),round(.025*w):round(.245*w)]
    if not crop.size:return []
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    mask=np.uint8((hsv[:,:,1]<60)&(hsv[:,:,2]>210))*255
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    boxes=[s for s in stats[1:] if .05*h<s[3]<.19*h and s[4]>.0004*h*w and .12<s[2]/s[3]<1.05 and .10*h<round(.055*h)+s[1]+s[3]/2<.18*h]
    boxes.sort(key=lambda s:s[0]);result=[]
    for x,y,width,height,area in boxes:
        glyph=mask[y:y+height,x:x+width]
        target=np.zeros((48,40),np.uint8)
        new_width=min(38,max(1,round(width*46/height)))
        small=cv2.resize(glyph,(new_width,46),interpolation=cv2.INTER_NEAREST)
        left=(40-new_width)//2;target[1:47,left:left+new_width]=small
        result.append(target>0)
    return result

