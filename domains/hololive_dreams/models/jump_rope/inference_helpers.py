"""Runtime-only history composition and ROI geometry."""
import numpy as np

def composite(image,older,newer):
    out=image.copy()
    # OpenCV BGR: older orange and faint; newer cyan and stronger.
    for mask,color,alpha in [(older,(0,140,255),.12),(newer,(255,230,0),.25)]:
        y,x=np.nonzero(mask)
        if len(x):
            values=out[y,x].astype(np.float64)
            values=values*(1-alpha)+np.asarray(color,np.float64)*alpha
            out[y,x]=np.clip(np.rint(values),0,255).astype(np.uint8)
    return out


def roi_bounds(shape,bottom=540):
    h,w=shape[:2]
    return round(w*240/1280),0,round(w*1120/1280),round(h*bottom/720)
