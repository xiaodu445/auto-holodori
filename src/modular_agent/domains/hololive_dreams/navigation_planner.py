"""Conservative annotation-based planning and passive route progress proposals."""
import hashlib
import heapq
import json
import math
import cv2
import numpy as np
from .patrol import Decision,MotionCalibration,PatrolSettings


def annotation_signature(project):
    data = dict(map=project.data['map']['sha256'],points=project.data['points'],regions=project.data['regions'],
                jumps=project.data['jumps'],route=project.route)
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()


def clear_line(mask,a,b):
    h,w = mask.shape
    for point in (a,b):
        if len(point)!=2 or not all(math.isfinite(v) for v in point) or not 0<=point[0]<w or not 0<=point[1]<h:return False
    samples = np.linspace(a,b,max(2,int(math.dist(a,b)*2)+1))
    for convert in (np.floor,np.ceil):
        x,y = convert(samples).astype(int).T
        if not np.all((x>=0)&(y>=0)&(x<w)&(y<h)) or not np.all(mask[y,x]>0):return False
    # Also guard the two crossed neighbours at diagonal pixel boundaries.
    low,high = np.floor(samples).astype(int),np.ceil(samples).astype(int)
    return bool(np.all(mask[low[:,1],high[:,0]]>0) and np.all(mask[high[:,1],low[:,0]]>0))


def simplify(points,mask):
    points = [list(map(float,p)) for i,p in enumerate(points) if not i or math.dist(points[i-1],p)>.001]
    if len(points)<3:return points
    result = [points[0]];i = 0
    while i<len(points)-1:
        j = min(len(points)-1,i+64)
        while j>i+1 and not clear_line(mask,points[i],points[j]):j -= 1
        result.append(points[j]);i = j
    return result


class WalkPlanner:
    def __init__(self,mask,jumps=(),*,cell=4,clearance=2):
        if type(cell) is not int or not 1<=cell<=16 or type(clearance) is not int or not 0<=clearance<=30:
            raise ValueError('网格应为1～16像素，安全边距为0～30像素')
        self.cell = cell;self.mask = (mask>127).astype(np.uint8)*255
        if clearance:self.mask = cv2.erode(self.mask,np.ones((2*clearance+1,)*2,np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)
        h,w = self.mask.shape;self.rows,self.cols = h//cell,w//cell
        if min(self.rows,self.cols)<1:raise ValueError('地图小于规划网格')
        self.grid = self.mask[:self.rows*cell,:self.cols*cell].reshape(self.rows,cell,self.cols,cell).min(axis=(1,3))>0
        self.portals = {};self.ignored_jumps = []
        for jump in jumps:
            if not jump.get('verified'):continue
            try:a,b = self.node(jump['start']),self.node(jump['end'])
            except ValueError:self.ignored_jumps.append(jump['name']);continue
            if a==b:continue
            self.portals.setdefault(a,[]).append((b,jump,max(math.dist(jump['start'],jump['end']),math.dist(self.center(a),self.center(b)))+8))

    def node(self,xy):
        x,y = xy
        if not all(math.isfinite(v) for v in xy) or not 0<=x<self.cols*self.cell or not 0<=y<self.rows*self.cell:
            raise ValueError('途经点超出规划网格')
        node = (int(y)//self.cell,int(x)//self.cell)
        if not self.grid[node]:raise ValueError('途经点位于未知/禁行区，或离墙太近；请调整标注或安全边距')
        return node

    def center(self,node):return [node[1]*self.cell+self.cell/2,node[0]*self.cell+self.cell/2]

    def search(self,start,goal):
        source,dest = self.node(start),self.node(goal)
        queue = [(0.,source)];cost = {source:0.};parents = {};expanded = 0
        while queue:
            _,current = heapq.heappop(queue);expanded += 1
            if expanded>500000:raise ValueError('规划搜索超过预算，请增大网格或缩小可走区')
            if current==dest:break
            edges = []
            for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)):
                node = (current[0]+dr,current[1]+dc)
                if 0<=node[0]<self.rows and 0<=node[1]<self.cols and self.grid[node]:edges.append((node,None,float(self.cell)))
            edges.extend(self.portals.get(current,()))
            for node,jump,weight in edges:
                candidate = cost[current]+weight
                if candidate<cost.get(node,math.inf):
                    cost[node] = candidate;parents[node] = (current,jump)
                    heuristic = math.dist(self.center(node),self.center(dest))
                    heapq.heappush(queue,(candidate+heuristic,node))
        else:raise ValueError('可走区不连通，找不到路线；请补标通道或检查定向跳跃')
        edges = [];current = dest
        while current!=source:
            previous,jump = parents[current];edges.append((previous,current,jump));current = previous
        edges.reverse();segments = [];walking = [list(start),self.center(source)]
        def flush():
            if walking:segments.append(dict(kind='walk',points=simplify(walking,self.mask)))
        for _,node,jump in edges:
            if jump:
                walking.append(jump['start']);flush()
                segments.append(dict(kind='jump',jump_id=jump['id'],name=jump['name'],points=[jump['start'],jump['end']],manual_required=True,verified=True))
                walking = [jump['end'],self.center(node)]
            else:walking.append(self.center(node))
        walking.append(list(goal));flush()
        return segments


def plan_project(project,*,cell=4,clearance=2,allow_jumps=False):
    points = project.route_points()
    if len(points)<2:raise ValueError('请先向路线添加至少两个途经点')
    if not any(r['kind']=='walkable' for r in project.data['regions']):raise ValueError('请先标注可走区；只标禁行区不能推断其他位置都可走')
    mask,_ = project.masks()
    if project.coverage is not None:mask[~project.coverage] = 0
    planner = WalkPlanner(mask,project.data['jumps'] if allow_jumps else (),cell=cell,clearance=clearance)
    pairs = list(zip(points,points[1:]))
    if project.route['loop']:pairs.append((points[-1],points[0]))
    segments = []
    for i,(a,b) in enumerate(pairs):
        try:parts = planner.search(a['xy'],b['xy'])
        except ValueError as error:raise ValueError(f"第{i+1}段 {a['name']} → {b['name']}：{error}") from error
        for part in parts:part['leg'] = i+1
        segments.extend(parts)
    flattened = []
    for segment in segments:
        for xy in segment['points']:
            if not flattened or math.dist(flattened[-1],xy)>.001:flattened.append(list(xy))
    distance = sum(math.dist(a,b) for segment in segments for a,b in zip(segment['points'],segment['points'][1:]))
    return dict(version=1,planning='annotation_astar',name=project.route['name'],map_sha256=project.data['map']['sha256'],
        annotation_signature=annotation_signature(project),cell=cell,clearance=clearance,loop=project.route['loop'],
        points=flattened,segments=segments,node_ids=list(project.route['nodes']),length_pixels=round(distance,1),
        requires_jump_execution=any(s['kind']=='jump' for s in segments),ignored_jumps=planner.ignored_jumps,
        reviewed=False,navigation_verified=False)


class RouteFollower:
    """Proposals only. Jump execution requires human handling and visual landing."""
    def __init__(self,plan,mask,calibration=None):
        if plan.get('planning')!='annotation_astar':raise ValueError('需要标注规划路线')
        if mask is None or mask.ndim!=2:raise ValueError('需要二维规划掩膜')
        self.mask = mask;self.motion = calibration or MotionCalibration();self.settings = PatrolSettings(arrival_radius=3,max_pulse=.12)
        self.actions = []
        for segment in plan['segments']:
            if segment['kind'] not in ('walk','jump') or not segment.get('points'):raise ValueError('无效路线动作')
            if segment['kind']=='jump' and len(segment['points'])!=2:raise ValueError('跳跃需要起跳点和落点')
            if not all(clear_line(mask,xy,xy) for xy in segment['points']):raise ValueError('路线端点超出可走区域')
            if segment['kind']=='walk' and not all(clear_line(mask,a,b) for a,b in zip(segment['points'],segment['points'][1:])):
                raise ValueError('步行段穿过未知/禁行区域')
            if segment['kind']=='jump':self.actions.append(dict(kind='jump',start=segment['points'][0],target=segment['points'][-1]))
            else:
                for xy in segment['points']:
                    if not self.actions or self.actions[-1]['target']!=xy:self.actions.append(dict(kind='walk',target=xy))
        if not self.actions:raise ValueError('路线为空')
        self.index = 0;self.last_frame = -1;self.landing_frames = 0;self.started_jump = False;self.halted = False

    def step(self,position,frame_id,now,*,free_scene=True,cancelled=False):
        if cancelled:self.halted = True
        if self.halted:return Decision('stop','cancelled')
        if self.index>=len(self.actions):return Decision('stop','route_traversed_collection_unverified')
        if frame_id<=self.last_frame or position is None or not position.valid or not 0<=now-position.t<=.5:
            self.landing_frames = 0
            return Decision('wait','fresh_localization_required')
        self.last_frame = frame_id
        if not free_scene:
            self.landing_frames = 0;return Decision('wait','free_scene_required')
        if not math.isfinite(position.x) or not math.isfinite(position.y):return Decision('wait','fresh_localization_required')
        action = self.actions[self.index];target = tuple(action['target']);xy = (position.x,position.y)
        if action['kind']=='jump':
            if not self.started_jump:
                if math.dist(xy,action['start'])>3:return Decision('wait','reach_jump_start_manually',target=tuple(action['start']))
                self.started_jump = True
            self.landing_frames = self.landing_frames+1 if math.dist(xy,target)<=3 else 0
            if self.landing_frames>=2:
                self.index += 1;self.started_jump = False;self.landing_frames = 0
                return Decision('wait','jump_landing_observed',target=target)
            return Decision('wait','manual_jump_required',target=target)
        if math.dist(xy,target)<=3:
            self.index += 1;return Decision('wait','waypoint_observed',target=target)
        if not clear_line(self.mask,xy,target):return Decision('wait','current_position_requires_replan',target=target)
        try:pulse = self.motion.pulse((target[0]-xy[0],target[1]-xy[1]),self.settings)
        except ValueError:return Decision('wait','motion_calibration_required',target=target)
        if not pulse:return Decision('wait','motion_cannot_reduce_error',target=target)
        keys,duration = pulse;landing = np.asarray(xy)+np.asarray(self.motion.vectors[keys[0]])*duration
        if not clear_line(self.mask,xy,landing):return Decision('wait','pulse_would_leave_walkable_area',target=target)
        return Decision('move','route_follow_shadow_proposal',keys,duration,target)
