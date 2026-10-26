"""Versioned offline annotations and manual route drafts. No game input."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .patrol_vision import read_image,write_image


def new_id():return uuid.uuid4().hex[:12]


def atomic_json(path,value):
    path = Path(path);temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NavigationProject:
    def __init__(self,path):
        self.path = Path(path).resolve()
        self.data = json.loads(self.path.read_text(encoding='utf-8-sig'))
        if self.data.get('version')!=1:raise ValueError('不支持的标注项目版本')
        self.map_path = self.path.parent/self.data['map']['file']
        if digest(self.map_path)!=self.data['map']['sha256']:
            raise ValueError('底图已变化。请恢复原底图或另建项目，不能直接沿用旧坐标。')
        self.image = read_image(self.map_path);self.history = []
        self.height,self.width = self.image.shape[:2]
        self.coverage = None
        if self.data['map'].get('coverage'):
            self.coverage = read_image(self.path.parent/self.data['map']['coverage'])[:,:,0]>127
        self.validate()

    @classmethod
    def create(cls,config_path,folder):
        config_path = Path(config_path).resolve();folder = Path(folder).resolve()
        config = json.loads(config_path.read_text(encoding='utf-8-sig'))
        source = config_path.parent/config['reference']
        image = read_image(source);h,w = image.shape[:2]
        folder.mkdir(parents=True,exist_ok=False)
        (folder/'map.png').write_bytes(source.read_bytes())
        metadata = dict(file='map.png',sha256=digest(source),width=w,height=h,
            source_config=str(config_path),source_image=str(source),coordinate_system='reference PNG pixels, origin top-left')
        if config.get('coverage'):
            (folder/'coverage.png').write_bytes((config_path.parent/config['coverage']).read_bytes())
            metadata['coverage'] = 'coverage.png'
        route = dict(id=new_id(),name='巡逻路线 1',nodes=[],loop=False)
        data = dict(version=1,map=metadata,points=[],regions=[],jumps=[],routes=[route],active_route=route['id'])
        atomic_json(folder/'project.json',data)
        return cls(folder/'project.json')

    def xy(self,point):
        if len(point)!=2 or not all(isinstance(v,(float,int)) and math.isfinite(v) for v in point):
            raise ValueError('坐标必须是有限的二维数值')
        x,y = map(float,point)
        if not 0<=x<self.width or not 0<=y<self.height:raise ValueError('标注坐标超出底图')
        return [min(self.width-.01,round(x,2)),min(self.height-.01,round(y,2))]

    def validate(self):
        if [self.width,self.height]!=[self.data['map']['width'],self.data['map']['height']]:raise ValueError('底图尺寸不匹配')
        ids = []
        for point in self.data['points']:
            ids.append(point['id']);self.xy(point['xy'])
            if point['kind'] not in ('treasure','waypoint'):raise ValueError('未知点位类型')
            seconds = point.get('refresh_seconds')
            if seconds is not None and (not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or seconds<=0):raise ValueError('无效刷新间隔')
        for region in self.data['regions']:
            ids.append(region['id'])
            if region['kind'] not in ('walkable','blocked') or len(region['polygon'])<3:raise ValueError('无效区域')
            for xy in region['polygon']:self.xy(xy)
            if cv2.contourArea(np.array(region['polygon'],np.float32))<1:raise ValueError('区域面积过小或顶点共线')
        for jump in self.data['jumps']:
            ids.append(jump['id']);self.xy(jump['start']);self.xy(jump['end'])
            if np.linalg.norm(np.array(jump['start'])-jump['end'])<1:raise ValueError('起跳点和落点过近')
            if jump.get('direction')!='start_to_end':raise ValueError('无效跳跃方向')
        points = {p['id'] for p in self.data['points']}
        for route in self.data['routes']:
            ids.append(route['id'])
            if any(node not in points for node in route['nodes']):raise ValueError('路线引用了不存在的点')
        if len(ids)!=len(set(ids)):raise ValueError('项目含重复标识符')
        if self.data['active_route'] not in {r['id'] for r in self.data['routes']}:raise ValueError('当前路线不存在')
        if self.coverage is not None and self.coverage.shape!=(self.height,self.width):raise ValueError('覆盖图尺寸不匹配')

    def change(self,operation):
        before = deepcopy(self.data)
        try:result = operation();self.validate()
        except Exception:self.data = before;raise
        self.history.append(before);self.history = self.history[-60:]
        return result

    def undo(self):
        if self.history:self.data = self.history.pop();return True
        return False

    @property
    def route(self):return next(r for r in self.data['routes'] if r['id']==self.data['active_route'])

    def find(self,identifier):
        for category in ('points','regions','jumps'):
            for item in self.data[category]:
                if item['id']==identifier:return category,item
        raise ValueError('未选择标注')

    def add_point(self,xy,kind='treasure'):
        point = dict(id=new_id(),kind=kind,xy=self.xy(xy),name='',notes='',refresh_seconds=None)
        count = sum(p['kind']==kind for p in self.data['points'])+1
        point['name'] = ('宝藏 ' if kind=='treasure' else '拐点 ')+str(count)
        self.change(lambda:self.data['points'].append(point))
        return point['id']

    def add_region(self,polygon,kind):
        item = dict(id=new_id(),kind=kind,polygon=[self.xy(p) for p in polygon],
                    name=('可走区' if kind=='walkable' else '禁行区')+str(len(self.data['regions'])+1),notes='')
        self.change(lambda:self.data['regions'].append(item));return item['id']

    def add_jump(self,start,end):
        item = dict(id=new_id(),name='跳跃 '+str(len(self.data['jumps'])+1),start=self.xy(start),end=self.xy(end),
                    direction='start_to_end',verified=False,notes='')
        self.change(lambda:self.data['jumps'].append(item));return item['id']

    def delete(self,identifier):
        category,item = self.find(identifier)
        def operation():
            self.data[category].remove(item)
            if category=='points':
                for route in self.data['routes']:route['nodes'] = [n for n in route['nodes'] if n!=identifier]
        self.change(operation)

    def add_to_route(self,identifier):
        category,_ = self.find(identifier)
        if category!='points':raise ValueError('路线只添加宝藏点或拐点')
        self.change(lambda:self.route['nodes'].append(identifier))

    def add_route_stop(self,xy,identifier=None):
        if identifier:
            self.add_to_route(identifier);return identifier
        point = dict(id=new_id(),kind='waypoint',xy=self.xy(xy),name='拐点 '+str(len(self.data['points'])+1),notes='',refresh_seconds=None)
        def operation():
            self.data['points'].append(point);self.route['nodes'].append(point['id'])
        self.change(operation);return point['id']

    def route_points(self,route=None):
        points = {p['id']:p for p in self.data['points']}
        return [points[n] for n in (route or self.route)['nodes']]

    def suggest_order(self):
        """Reorder a draft geometrically, preserving first point and duplicates."""
        remaining = self.route_points()
        if len(remaining)<3:return
        ordered = [remaining.pop(0)]
        while remaining:
            i = min(range(len(remaining)),key=lambda i:math.dist(ordered[-1]['xy'],remaining[i]['xy']))
            ordered.append(remaining.pop(i))
        self.change(lambda:self.route.update(nodes=[p['id'] for p in ordered]))

    def masks(self):
        walk = np.zeros((self.height,self.width),np.uint8);blocked = walk.copy()
        for region in self.data['regions']:
            polygon = np.rint(region['polygon']).astype(np.int32)
            cv2.fillPoly(walk if region['kind']=='walkable' else blocked,[polygon],255)
        walk[blocked>0] = 0
        return walk,blocked

    def route_report(self,route=None):
        route = route or self.route;points = self.route_points(route)
        pairs = list(zip(points,points[1:]))
        if route['loop'] and len(points)>1:pairs.append((points[-1],points[0]))
        walk,blocked = self.masks();warnings = []
        has_walk = any(r['kind']=='walkable' for r in self.data['regions'])
        if not has_walk:warnings.append('尚未标注可走区；路线仅为人工草稿。')
        length = 0.
        for i,(a,b) in enumerate(pairs):
            distance = math.dist(a['xy'],b['xy']);length += distance
            samples = np.linspace(a['xy'],b['xy'],max(2,int(distance*2)+1))
            xs = np.clip(np.rint(samples[:,0]).astype(int),0,self.width-1)
            ys = np.clip(np.rint(samples[:,1]).astype(int),0,self.height-1)
            if np.any(blocked[ys,xs]):warnings.append(f'第{i+1}段穿过禁行区，请添加绕行拐点。')
            elif has_walk and np.any(walk[ys,xs]==0):warnings.append(f'第{i+1}段经过未确认可走区域。')
            if self.coverage is not None and np.any(~self.coverage[ys,xs]):warnings.append(f'第{i+1}段经过底图缺口。')
        return dict(name=route['name'],point_count=len(points),length_pixels=round(length,1),warnings=warnings,
                    navigation_verified=False,planning='manual_polyline',loop=route['loop'])

    def save(self):
        self.validate()
        if self.path.exists():self.path.with_suffix('.json.bak').write_bytes(self.path.read_bytes())
        atomic_json(self.path,self.data)

    def export(self,plan=None):
        if plan is not None:
            from .navigation_planner import annotation_signature
            if plan.get('annotation_signature')!=annotation_signature(self):raise ValueError('标注或路线已变化，请重新规划后再导出')
        self.save()
        folder = self.path.parent/'exports'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        folder.mkdir(parents=True,exist_ok=False)
        data = deepcopy(self.data);data['reports'] = [self.route_report(r) for r in self.data['routes']]
        data['map']['project_file'] = str(self.path)
        atomic_json(folder/'navigation.json',data)
        (folder/'map.png').write_bytes(self.map_path.read_bytes())
        if self.data['map'].get('coverage'):
            (folder/self.data['map']['coverage']).write_bytes((self.path.parent/self.data['map']['coverage']).read_bytes())
        route = dict(points=[p['xy'] for p in self.route_points()],node_ids=list(self.route['nodes']),
            loop=self.route['loop'],reference='map.png',map_sha256=self.data['map']['sha256'],
            coordinate_system=self.data['map']['coordinate_system'],reviewed=False,report=self.route_report())
        atomic_json(folder/'route.json',route)
        atomic_json(folder/'treasures.json',dict(map_sha256=self.data['map']['sha256'],
            coordinate_system=self.data['map']['coordinate_system'],points=[p for p in self.data['points'] if p['kind']=='treasure']))
        atomic_json(folder/'routes.json',dict(map_sha256=self.data['map']['sha256'],routes=[dict(
            id=r['id'],name=r['name'],points=[p['xy'] for p in self.route_points(r)],node_ids=r['nodes'],
            loop=r['loop'],report=self.route_report(r)) for r in self.data['routes']]))
        walk,blocked = self.masks()
        write_image(folder/'walk-mask.png',walk);write_image(folder/'blocked-mask.png',blocked)
        self.render_overlay().save(folder/'annotations.png')
        source = Path(self.data['map']['source_config'])
        if source.is_file():
            config = json.loads(source.read_text(encoding='utf-8-sig'))
            config.update(reference='map.png',reference_reviewed=False)
            if self.data['map'].get('coverage'):config['coverage'] = self.data['map']['coverage']
            else:config.pop('coverage',None)
            if config.get('input_mask'):
                target = folder/'global-input-mask.png'
                target.write_bytes((source.parent/config['input_mask']).read_bytes());config['input_mask'] = target.name
            atomic_json(folder/'patrol-config.json',config)
        if plan is not None:
            from .navigation_planner import WalkPlanner
            plan = deepcopy(plan);plan.update(reference='map.png',planning_mask='planning-mask.png')
            walk,_ = self.masks()
            if self.coverage is not None:walk[~self.coverage] = 0
            planner = WalkPlanner(walk,cell=plan['cell'],clearance=plan['clearance'])
            write_image(folder/'planning-mask.png',planner.mask)
            atomic_json(folder/'planned-route.json',plan)
            self.render_overlay(plan).save(folder/'planned-route.png')
        return folder

    def render_overlay(self,plan=None):
        image = Image.fromarray(cv2.cvtColor(self.image,cv2.COLOR_BGR2RGB)).convert('RGBA')
        layer = Image.new('RGBA',image.size);draw = ImageDraw.Draw(layer)
        try:font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',13)
        except OSError:font = ImageFont.load_default()
        for region in self.data['regions']:
            color = (40,210,110) if region['kind']=='walkable' else (245,65,70)
            draw.polygon([tuple(p) for p in region['polygon']],fill=(*color,45),outline=(*color,255),width=2)
        def arrow(a,b,color,width=2):
            a,b = np.asarray(a,float),np.asarray(b,float)
            draw.line([tuple(a),tuple(b)],fill=color,width=width)
            vector = b-a;size = np.linalg.norm(vector)
            if size>1:
                unit = vector/size;side = np.array([-unit[1],unit[0]])
                draw.polygon([tuple(b),tuple(b-unit*10+side*4),tuple(b-unit*10-side*4)],fill=color)
        route = self.route_points();pairs = list(zip(route,route[1:]))
        if self.route['loop'] and len(route)>1:pairs.append((route[-1],route[0]))
        if plan is None:
            for a,b in pairs:arrow(a['xy'],b['xy'],(80,170,255,255),3)
        else:
            for segment in plan['segments']:
                for a,b in zip(segment['points'],segment['points'][1:]):arrow(a,b,(220,100,255,255) if segment['kind']=='jump' else (30,235,150,255),3)
        for jump in self.data['jumps']:arrow(jump['start'],jump['end'],(220,100,255,255),3)
        for p in self.data['points']:
            x,y = p['xy'];radius = 6 if p['kind']=='treasure' else 4
            draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=(255,190,30,255) if p['kind']=='treasure' else (60,180,255,255),outline='black',width=1)
            draw.text((x+8,y-8),p['name'],fill='white',font=font,stroke_width=1,stroke_fill='black')
        for i,p in enumerate(route):draw.text((p['xy'][0]-10,p['xy'][1]+7),str(i+1),font=font,fill='white',stroke_width=1,stroke_fill='black')
        return Image.alpha_composite(image,layer).convert('RGB')
