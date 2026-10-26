"""Screen-space overlay exclusion. No terrain is recolored or synthesized."""
import cv2
import numpy as np


def exclude_random_markers(image,mask):
    """Exclude small vivid pink/red/lime circular badges with a pale outline.

    Cyan facilities and broad green terrain are retained. This is a conservative
    appearance filter, not a complete semantic marker classifier.
    """
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    hue,saturation,value = cv2.split(hsv)
    color = (((hue>=140)|(hue<=8)|((hue>=35)&(hue<=75)))&
             (saturation>160)&(value>150)).astype(np.uint8)
    white = (saturation<50)&(value>220)
    count,labels,stats,_ = cv2.connectedComponentsWithStats(color)
    result = mask.copy();found = 0
    factor = image.shape[1]/164
    for label in range(1,count):
        x,y,w,h,area = stats[label]
        if not 6*factor**2<=area<=120*factor**2 or not .65<=w/h<=1.5 or max(w,h)>18*factor:
            continue
        component = (labels==label).astype(np.uint8)
        contours,_ = cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        perimeter = cv2.arcLength(contours[0],True)
        if 4*np.pi*area/max(perimeter**2,1)<.5:
            continue
        expanded = cv2.dilate(component,np.ones((5,5),np.uint8))>0
        ring = expanded&(component==0)
        if np.mean(white[ring])<.18:
            continue
        result[expanded] = 0;found += 1
    return result,found


def exclude_view_cone(image, mask, half_angle=58):
    """Find the near-white player pointer outside its circular ring.

    Yellow ground is deliberately not used as evidence. Ambiguous/missing
    pointers fail closed: this frame is not eligible for map composition.
    Angles follow image coordinates: right=0, down=90 degrees.
    """
    h,w = mask.shape
    yy,xx = np.mgrid[:h,:w]
    dx,dy = (xx-w/2)/(w/164),(yy-h/2)/(h/164)
    radius = np.hypot(dx,dy);angle = np.arctan2(dy,dx)
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    white = (hsv[:,:,1]<12)&(hsv[:,:,2]>240)&(radius>17)&(radius<27)
    scores = []
    white_angles = angle[white]
    white_weights = (radius-17)[white]
    for theta in np.deg2rad(np.arange(0,360,5)):
        # Only the handful of white pointer pixels vote. Evaluating complex
        # exponentials for the entire tile 72 times stalled passive tracking.
        distance = np.abs((white_angles-theta+np.pi)%(2*np.pi)-np.pi)
        scores.append(float(np.sum(white_weights[distance<np.deg2rad(18)])))
    peak = int(np.argmax(scores))
    rival = max(s for i,s in enumerate(scores) if min(abs(i-peak),72-abs(i-peak))>12)
    if scores[peak]<35 or rival>scores[peak]*.5:
        return np.zeros_like(mask),dict(valid=False,reason='pointer_direction_ambiguous',peak=scores[peak],rival=rival)
    chosen = white&(np.abs((angle-np.deg2rad(peak*5)+np.pi)%(2*np.pi)-np.pi)<np.deg2rad(28))
    weight = np.maximum(radius-17,0)*chosen
    heading = np.arctan2(np.sum(np.sin(angle)*weight),np.sum(np.cos(angle)*weight))
    distance = np.abs((angle-heading+np.pi)%(2*np.pi)-np.pi)
    result = mask.copy()
    result[distance<np.deg2rad(half_angle)] = 0
    return result,dict(valid=True,heading_degrees=float(np.rad2deg(heading)%360),
                       half_angle_degrees=half_angle,excluded_pixels=int(np.count_nonzero((mask>0)&(result==0))))
