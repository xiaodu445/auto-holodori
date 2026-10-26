"""Known kitchen summary/reward/event/replay menus; no generic background clicks."""
from pathlib import Path
import math
import cv2,numpy as np
from modular_agent.domains.hololive_dreams.interaction import RetryBudget,policy_for
STAGES=('score_next','reward_ok','event_next','play')
ANCHORS={'score_next':(710,465,850,515),'reward_ok':(642,328,785,366),'event_next':(656,263,808,295),'play':(30,15,320,195)}
class LoopPageDetector:
    def __init__(self,folder):
        folder=Path(folder);self.header=cv2.imread(str(folder/'menu-header.png'),0);self.anchors={s:cv2.imread(str(folder/(s+'-anchor.png')),0) for s in STAGES}
        self.buttons={s:cv2.imread(str(folder/(s+'-button.png')),0) for s in STAGES}
    @staticmethod
    def score(image,template):
        if template is None or image.shape[0]<template.shape[0] or image.shape[1]<template.shape[1]:return 0.
        return float(cv2.minMaxLoc(cv2.matchTemplate(image,template,cv2.TM_CCOEFF_NORMED))[1])
    def read(self,image):
        small=cv2.resize(image,(1260,708));gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        best=None
        for stage in STAGES:
            a,b,c,d=ANCHORS[stage];region=gray[max(0,b-12):min(708,d+12),max(0,a-12):min(1260,c+12)]
            anchor=self.score(region,self.anchors[stage])
            if anchor<.83:continue
            button=self.score(gray[610:680,980:1150],self.buttons[stage])
            patch=small[620:667,985:1155];blue=(patch[:,:,0]>160)&(patch[:,:,1]>100)&(patch[:,:,2]<140)
            enabled=button>=.85 and float(blue.mean())>.35
            row=dict(stage=stage,scene='loop_'+stage,enabled=enabled,anchor_score=anchor,button_score=button,point=(.845,.908))
            if best is None or row['anchor_score']+row['button_score']>best['anchor_score']+best['button_score']:best=row
        if best is None and self.score(gray[5:125,10:300],self.header)>=.85:
            return dict(stage='waiting',scene='loop_waiting',enabled=False,point=(.845,.908))
        return best
class LoopMenuController:
    """Three source-confirmed attempts per page episode; no global run timeout."""
    def __init__(self):self.stage=None;self.streak=0;self.last_frame=-1;self.budget=None;self.since=None;self.last_seen=-math.inf
    def observe(self,page,frame_id,now,stopped=False):
        if not page:
            if now-self.last_seen>=.5:
                self.stage=None;self.streak=0;self.last_frame=-1;self.budget=None;self.since=None
            return False
        if page['stage'] not in STAGES:return False
        self.last_seen=now
        stage=page['stage']
        if stage!=self.stage:
            self.stage=stage;self.streak=0;self.since=now;self.last_frame=-1
            self.budget=RetryBudget(policy_for('kitchen_loop_'+stage,retry_interval=2,max_attempts=3))
        if frame_id!=self.last_frame:self.streak+=1;self.last_frame=frame_id
        return bool(not stopped and self.streak>=2 and now-self.since>=.5 and self.budget.ready(now,source_valid=True,enabled=page['enabled']))
    def sent(self,now):self.budget.sent(now)
    @property
    def exhausted(self):return self.budget is not None and self.budget.attempts>=3
