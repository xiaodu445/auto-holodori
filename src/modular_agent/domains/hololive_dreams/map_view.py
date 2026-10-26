"""Detect a map zoom knob and corroborating horizontal rail, never guess a click."""
import cv2
import numpy as np
def detect_zoom(image,origin=(0,0)):
 h,w=image.shape[:2]
 left,top=int(w*.74),int(h*.84)
 roi=image[top:int(h*.99),left:int(w*.99)]
 hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
 red=np.uint8(((hsv[:,:,0]<12)|(hsv[:,:,0]>170))&(hsv[:,:,1]>65)&(hsv[:,:,2]>135))*255
 contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
 candidates=[]
 for c in contours:
  x,y,cw,ch=cv2.boundingRect(c)
  if not (.014*w<=cw<=.045*w and .7<=cw/max(1,ch)<=1.35): continue
  area=cv2.contourArea(c)
  if area<.45*cw*ch: continue
  cx,cy=x+cw/2,y+ch/2
  band=roi[max(0,int(cy)-6):min(roi.shape[0],int(cy)+7)]
  edges=cv2.Canny(band,40,110)
  lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=25,minLineLength=int(w*.06),maxLineGap=int(w*.04))
  if lines is None: continue
  horizontal=[line for line in np.asarray(lines).reshape(-1,4) if abs(int(line[3])-int(line[1]))<=2]
  if not horizontal: continue
  rail_left=min(int(l[0]) for l in horizontal)
  rail_right=max(int(l[2]) for l in horizontal)
  if rail_right-rail_left<w*.12: continue
  rail_left=min(rail_left,int(cx))
  rail_right=max(rail_right,int(cx))
  candidates.append({'knob':{'x':origin[0]+left+round(cx),'y':origin[1]+top+round(cy)},
                     'minimum':{'x':origin[0]+left+rail_left+round(cw/2),'y':origin[1]+top+round(cy)},
                     'rail_width':rail_right-rail_left})
 return max(candidates,key=lambda d:d['rail_width']) if candidates else None
