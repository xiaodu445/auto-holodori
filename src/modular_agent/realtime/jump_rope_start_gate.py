"""Local Go-banner gate: fail closed without a witnessed banner exit."""
import cv2
import numpy as np

class GoStartGate:
    def __init__(self,confirm_frames=3,clear_frames=3,roi=(0,0,1,1)):
        self.confirm_frames=confirm_frames;self.clear_frames=clear_frames;self.roi=roi;self.roi=roi
        self.seen=0;self.clear=0;self.armed=False;self.started_at=None
    def update(self,image,now):
        if self.started_at is not None:return True
        h,w=image.shape[:2];l,t,r,b=self.roi;h=h/(b-t);w=w/(r-l)
        crop=image[max(0,round((.20-t)*h)):round((.58-t)*h),max(0,round((.35-l)*w)):round((.66-l)*w)]
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(20,130,190),(38,255,255))
        n,_,stats,_=cv2.connectedComponentsWithStats(mask)
        visible=any(s[cv2.CC_STAT_WIDTH]>.08*w and s[cv2.CC_STAT_WIDTH]/max(1,s[cv2.CC_STAT_HEIGHT])>1.35 and s[cv2.CC_STAT_AREA]>.0025*h*w for s in stats[1:])
        self.seen=self.seen+1 if visible else 0
        if self.seen>=self.confirm_frames:self.armed=True
        self.clear=self.clear+1 if self.armed and not visible else 0
        if self.clear>=self.clear_frames:self.started_at=now
        return self.started_at is not None

def waiting_observation():
    return dict(valid=False,avatar_valid=False,rope_valid=False,whole_curve=[],whole_point_states=[],whole_observed_points=[],whole_coverage=0.,phase_visual_quality=0.,motion_state='waiting_for_start',tracking_status='waiting_for_start',model_exists=False,selected_hypothesis=None,mode_candidate=None,phase_alternatives=[],phase_estimate=dict(locked=False,phase_unwrapped=None,phase=None,clock_rate=0.,rate=0.,template_acceleration=0.,confidence=0.,continuation='start_gate_closed'))
