"""Map-bound route experience and bounded input prediction; no native input."""
from collections import deque
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import uuid
import numpy as np
import cv2
from .navigation_planner import clear_line
from .camera_navigation import angle_error,CameraHeading


def route_key(plan):
    payload=dict(map=plan['map_sha256'],name=plan.get('name'),segments=plan['segments'])
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


class RouteExperience:
    def __init__(self,plan,path):
        self.key=route_key(plan);self.map=plan['map_sha256'];self.path=Path(path)
        self.samples=deque(maxlen=16);self.fired=set();self.jumps=[]
        if self.path.exists():
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('route_key')!=self.key or value.get('map_sha256')!=self.map:raise ValueError('路线记忆与当前地图/路线不匹配')
            for item in value.get('jumps',[]):
                if (len(item['xy'])!=2 or not all(math.isfinite(v) for v in (*item['xy'],item['heading']))
                        or type(item['action_index']) is not int):raise ValueError('跳跃记忆损坏')
                self.jumps.append(item)

    def observe(self,position,heading,index,scene=True):
        self.samples.append(dict(t=position.t,xy=[position.x,position.y],valid=bool(scene and position.valid and position.reason!='input_prediction_bridge'
            and heading and heading.valid and heading.source!='input_prediction_bridge' and abs(position.t-heading.t)<=.5),
            heading=heading.degrees if heading else 0,index=index))

    def learn(self,t):
        before=next((s for s in reversed(self.samples) if s['t']<=t),None)
        after=next((s for s in self.samples if s['t']>=t),None)
        if not before or not after or not before['valid'] or not after['valid']:return None
        gap=after['t']-before['t']
        if gap>.5 or before['index']!=after['index'] or abs(angle_error(after['heading'],before['heading']))>30:return None
        if math.dist(before['xy'],after['xy'])>90*gap+3:return None
        alpha=(t-before['t'])/gap if gap>0 else 0
        xy=[a+(b-a)*alpha for a,b in zip(before['xy'],after['xy'])]
        heading=(before['heading']+angle_error(after['heading'],before['heading'])*alpha)%360
        if math.dist(before['xy'],after['xy'])>=3:
            heading=math.degrees(math.atan2(after['xy'][1]-before['xy'][1],after['xy'][0]-before['xy'][0]))%360
        for item in self.jumps:
            if item['action_index']==before['index'] and math.dist(xy,item['xy'])<5 and abs(angle_error(heading,item['heading']))<30:
                self.fired.add(item['id']);return dict(item,duplicate=True)
        if len(self.jumps)>=1000:raise ValueError('路线跳跃记忆超过1000处')
        item=dict(id=uuid.uuid4().hex[:12],xy=xy,heading=heading,action_index=before['index'],
                  source='physical_space',landing_verified=False)
        self.jumps.append(item);self.fired.add(item['id']);self.save()
        return item

    def save(self):atomic_json(self.path,dict(version=1,route_key=self.key,map_sha256=self.map,jumps=self.jumps))

    def due(self,position,heading,index,now):
        if (not position.valid or position.reason=='input_prediction_bridge' or not heading or not heading.valid
                or heading.source=='input_prediction_bridge' or not 0<=now-position.t<=.5 or not 0<=now-heading.t<=.5):return None
        for item in self.jumps:
            if item['id'] in self.fired or item['action_index']!=index:continue
            dx=item['xy'][0]-position.x;dy=item['xy'][1]-position.y;theta=math.radians(heading.degrees)
            ahead=dx*math.cos(theta)+dy*math.sin(theta)
            if math.hypot(dx,dy)<=6 and ahead>=-3 and abs(angle_error(heading.degrees,item['heading']))<=30:
                # An input attempt is consumed once, even if no landing follows.
                return item
        return None


class SemiInertialEstimate:
    """Snap to every valid visual pose; optionally bridge <=0.25s in cruise.

    Keeps a separate prediction/innovation for comparison, rather than claiming
    that a model pose was observed. No dead reckoning starts a new movement.
    """
    def __init__(self,speed,slope):
        self.speed=speed;self.slope=slope;self.previous=None;self.xy=None;self.yaw=None
        self.visual_t=None;self.heading_t=None;self.error_sum=0.;self.error_count=0;self.error_max=0.;self.bridges=0
        self.inertial_xy=None;self.inertial_yaw=None;self.inertial_error=None;self.inertial_max=0.

    def update(self,position,heading,meter,*,mode='visual',cruising=False,scene=True):
        t=position.t;predicted=None;innovation=None
        if self.previous is not None and self.xy is not None:
            dw=max(0,meter['w_seconds']-self.previous['w_seconds']);dx=meter['mouse_counts']-self.previous['mouse_counts']
            rotation=dx*self.slope
            if self.inertial_xy is not None:
                theta=math.radians(self.inertial_yaw+rotation*.5)
                self.inertial_xy=[self.inertial_xy[0]+math.cos(theta)*dw*self.speed,self.inertial_xy[1]+math.sin(theta)*dw*self.speed]
                self.inertial_yaw=(self.inertial_yaw+rotation)%360
            if self.yaw is not None:
                theta=math.radians(self.yaw+rotation*.5)
                predicted=[self.xy[0]+math.cos(theta)*dw*self.speed,self.xy[1]+math.sin(theta)*dw*self.speed]
                self.yaw=(self.yaw+rotation)%360
        if heading and heading.valid:self.yaw=heading.degrees;self.heading_t=t
        if position.valid and scene:
            if predicted is not None:
                innovation=math.dist(predicted,(position.x,position.y))
                self.error_sum+=innovation;self.error_max=max(self.error_max,innovation);self.error_count+=1
            self.xy=[position.x,position.y];self.visual_t=t
            if self.inertial_xy is None and heading and heading.valid:
                self.inertial_xy=self.xy.copy();self.inertial_yaw=heading.degrees
            if self.inertial_xy is not None:
                self.inertial_error=math.dist(self.inertial_xy,self.xy);self.inertial_max=max(self.inertial_max,self.inertial_error)
        elif predicted is not None:self.xy=predicted
        self.previous=meter.copy()
        gap=t-self.visual_t if self.visual_t is not None else math.inf
        heading_gap=t-self.heading_t if self.heading_t is not None else math.inf
        out_position=position;out_heading=heading
        if mode=='fused' and cruising and scene and 0<=gap<=.25 and heading_gap<=.25:
            if not position.valid and self.xy is not None:
                out_position=replace(position,x=self.xy[0],y=self.xy[1],valid=True,reason='input_prediction_bridge')
                self.bridges+=1
            if heading and not heading.valid and self.yaw is not None:
                out_heading=CameraHeading(self.yaw,t,True,'input_prediction_bridge',0)
        return out_position,out_heading,dict(visual=[position.x,position.y] if position.valid else None,
            prediction=predicted,fused=[out_position.x,out_position.y] if out_position.valid else None,
            inertial_position=self.inertial_xy.copy() if self.inertial_xy is not None else None,inertial_error_pixels=self.inertial_error,
            innovation_pixels=innovation,visual_gap=gap if math.isfinite(gap) else None,
            used_prediction=out_position.reason=='input_prediction_bridge' or bool(out_heading and out_heading.source=='input_prediction_bridge'))

    def summary(self):return dict(samples=self.error_count,mean_innovation=self.error_sum/max(1,self.error_count),
                                 max_innovation=self.error_max,prediction_bridges=self.bridges,
                                 inertial_end_error=self.inertial_error,inertial_max_error=self.inertial_max)


class Demonstration:
    def __init__(self,plan):self.plan=plan;self.points=[];self.jumps=[];self.gap=False;self.interrupted=False

    def observe(self,position,scene=True):
        if not scene or not position.valid:
            if self.points:self.gap=True
            return
        if self.points and position.t-self.points[-1]['t']>.6:self.gap=True
        if self.points and self.gap:self.interrupted=True
        self.points.append(dict(xy=[position.x,position.y],t=position.t))
        if len(self.points)>30000:raise ValueError('示教轨迹超过30000帧')

    def save(self,path):
        path=Path(path)
        length=sum(math.dist(a['xy'],b['xy']) for a,b in zip(self.points,self.points[1:]))
        if self.interrupted or self.gap or len(self.points)<2 or length<3:
            path=path.with_name(path.stem+'-candidate-'+uuid.uuid4().hex[:8]+path.suffix)
        atomic_json(path,dict(version=1,base_route_key=route_key(self.plan),map_sha256=self.plan['map_sha256'],
            points=self.points,jumps=self.jumps,interrupted=self.interrupted or self.gap,landing_verified=False))
        return path


def demonstration_plan(base,data,mask):
    if data.get('base_route_key')!=route_key(base) or data.get('map_sha256')!=base['map_sha256']:raise ValueError('示教与当前地图/路线不匹配')
    if data.get('interrupted'):raise ValueError('示教途中定位中断，请重新录制，不能连接未知路段')
    points=np.asarray([p['xy'] for p in data['points']],np.float32)
    if len(points)<2 or not np.all(np.isfinite(points)) or sum(math.dist(a,b) for a,b in zip(points,points[1:]))<3:raise ValueError('示教轨迹过短')
    # Preserve manually chosen detours; never replace them with a visibility
    # shortcut merely because an incompletely annotated mask looks walkable.
    simplified=cv2.approxPolyDP(points.reshape(-1,1,2),1.5,False).reshape(-1,2).tolist()
    if any(not clear_line(mask,a,b) for a,b in zip(simplified,simplified[1:])):raise ValueError('示教穿过未知/禁行区，需要先补标注')
    plan=dict(base,segments=[dict(kind='walk',points=simplified)],points=simplified,demonstration=True)
    return plan


def seed_demonstration_jumps(memory,data,actions):
    if memory.jumps:return
    for original in data.get('jumps',[]):
        best=None
        for index in range(1,len(actions)):
            a=np.asarray(actions[index-1]['target'],float);b=np.asarray(actions[index]['target'],float)
            delta=b-a;length=float(delta@delta)
            if length<1:continue
            bearing=math.degrees(math.atan2(delta[1],delta[0]))
            if abs(angle_error(bearing,original['heading']))>45:continue
            alpha=float(np.clip((np.asarray(original['xy'])-a)@delta/length,0,1))
            distance=math.dist(original['xy'],a+alpha*delta)
            if distance<=6 and (best is None or distance<best[0]):best=(distance,index)
        if best is not None:memory.jumps.append(dict(original,action_index=best[1]))
    if memory.jumps:memory.save()
