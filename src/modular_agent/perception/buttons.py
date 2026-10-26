"""Bounded visual button candidates. These are shapes, not verified clickable controls."""
import cv2
from .report import Rect

class ButtonDetector:
    def __init__(self,max_candidates=100): self.max_candidates=max_candidates

    def detect(self,image,origin=(0,0)):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        edges=cv2.Canny(gray,60,160)
        edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)))
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        candidates=[]
        height,width=gray.shape
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            if not (30<=w<=width*.85 and 15<=h<=height*.3 and .8<=w/h<=15): continue
            if cv2.contourArea(contour)/max(1,w*h)<.65: continue
            perimeter=cv2.arcLength(contour,True)
            approx=cv2.approxPolyDP(contour,.03*perimeter,True)
            if not 4<=len(approx)<=8: continue
            bounds=Rect(x+origin[0],y+origin[1],w,h)
            candidates.append(bounds)
        candidates.sort(key=lambda b:b.area)
        kept=[]
        for bounds in candidates:
            if any(bounds.iou(other)>.7 for other in kept): continue
            kept.append(bounds)
            if len(kept)>=self.max_candidates: break
        return [{'id':f'cv-button:{i}','label':'','bounds':b.to_dict(),
            'confidence':.35,'source':'cv_shape','semantic_confirmed':False,
            'enabled':None,'text_ids':[]} for i,b in enumerate(kept)]
