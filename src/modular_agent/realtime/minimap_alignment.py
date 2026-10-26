"""Offline human-assisted translation graph and non-destructive map export.

No game capture/input. Human anchors and paired landmarks constrain a smooth
correction of the recorded trajectory. Coordinates remain normalized tile pixels.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict,replace
import base64
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import MinimapMapper,MapperSettings,MappingResult
from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image


def atomic_json(path,data):
    path = Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def matching_placements(recording,search_root):
    """Prefer a compatible rebuilt trajectory, never match by frame count alone."""
    source = load_rows(Path(recording)/'frames.jsonl')
    for path in sorted(Path(search_root).glob('rebuild-*/frames.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            rows = load_rows(path)
            if len(rows)==len(source) and all(abs(a['t']-b['t'])<1e-8 for a,b in zip(rows,source)):
                return path
        except (OSError,ValueError,KeyError):
            continue
    return Path(recording)/'frames.jsonl'


def solve_graph(count,edges,anchors,*,tolerance=1e-8,max_iterations=5000):
    """Preconditioned CG on a sparse translation graph (no SciPy dependency).

    edges=(i,j,desired correction_j-correction_i,weight); anchors=(i,value,weight).
    Return the least-squares correction, iterations and honest residuals.
    """
    if count<1:
        raise ValueError('empty pose graph')
    ids_i = np.array([e[0] for e in edges],dtype=int)
    ids_j = np.array([e[1] for e in edges],dtype=int)
    weights = np.array([e[3] for e in edges],dtype=float)
    diagonal = np.full(count,1e-10)
    rhs = np.zeros((count,2),dtype=float)
    anchor_diag = np.full(count,1e-10)
    for i,value,weight in anchors:
        if not 0<=i<count or weight<=0 or not np.all(np.isfinite(value)):
            raise ValueError('invalid graph anchor')
        anchor_diag[i] += weight;rhs[i] += np.asarray(value)*weight
    if edges:
        if min(ids_i.min(),ids_j.min())<0 or max(ids_i.max(),ids_j.max())>=count or np.any(weights<=0):
            raise ValueError('invalid graph edge')
        values = np.array([e[2] for e in edges],dtype=float)
        if not np.all(np.isfinite(values)) or not np.all(np.isfinite(weights)):
            raise ValueError('nonfinite graph edge')
        diagonal = anchor_diag+np.bincount(ids_i,weights,minlength=count)+np.bincount(ids_j,weights,minlength=count)
        for axis in range(2):
            v = weights*values[:,axis]
            rhs[:,axis] += np.bincount(ids_j,v,minlength=count)-np.bincount(ids_i,v,minlength=count)
    else:
        diagonal = anchor_diag.copy()
    def multiply(vector):
        out = anchor_diag*vector
        if edges:
            diff = weights*(vector[ids_i]-vector[ids_j])
            out += np.bincount(ids_i,diff,minlength=count)-np.bincount(ids_j,diff,minlength=count)
        return out
    solution = np.zeros((count,2),dtype=float);iterations = 0
    for axis in range(2):
        b = rhs[:,axis];x = np.zeros(count);r = b.copy();z = r/diagonal;p = z.copy()
        rz = float(r@z);limit = tolerance*max(1,float(np.linalg.norm(b)))
        for iteration in range(min(max_iterations,max(100,count*5))):
            if np.linalg.norm(r)<=limit:
                break
            ap = multiply(p);denom = float(p@ap)
            if denom<=0 or not math.isfinite(denom):
                raise RuntimeError('alignment solver did not converge')
            alpha = rz/denom;x += alpha*p;r -= alpha*ap
            z = r/diagonal;new_rz = float(r@z)
            p = z+(new_rz/rz)*p;rz = new_rz
            iterations = max(iterations,iteration+1)
        if np.linalg.norm(multiply(x)-b)>limit*10:
            raise RuntimeError('alignment solver iteration budget exhausted')
        solution[:,axis] = x
    return solution,iterations


class AlignmentProject:
    def __init__(self,recording,placements=None,project_file=None,*,from_zero=False):
        self.recording = Path(recording).resolve()
        self.placements = Path(placements or self.recording/'frames.jsonl').resolve()
        self.raw = load_rows(self.recording/'frames.jsonl');rows = load_rows(self.placements)
        if not self.raw or len(rows)!=len(self.raw) or any(abs(a['t']-b['t'])>1e-8 for a,b in zip(rows,self.raw)):
            raise ValueError('trajectory does not match this recording')
        self.ids = [int(row.get('frame_id',i+1)) for i,row in enumerate(self.raw)]
        if len(set(self.ids))!=len(self.ids):
            raise ValueError('duplicate frame IDs')
        self.lookup = {fid:i for i,fid in enumerate(self.ids)}
        self.base = np.array([[row['x'],row['y']] for row in rows],dtype=float)
        self.accepted = [bool(row.get('accepted')) for row in rows]
        if not np.all(np.isfinite(self.base)):
            raise ValueError('nonfinite trajectory')
        self.hashes = dict(recording=digest(self.recording/'frames.jsonl'),placements=digest(self.placements))
        self.project_file = Path(project_file) if project_file else None
        self.settings = MapperSettings()
        if (self.placements.parent/'mapping.json').exists():
            meta = json.loads((self.placements.parent/'mapping.json').read_text(encoding='utf-8'))
            self.settings = MapperSettings(**meta.get('settings',{}))
        self.data = dict(version=1,recording=str(self.recording),placements=str(self.placements),
                         hashes=self.hashes,anchors={},pairs=[],included={},view={},
                         workflow='manual' if from_zero else 'assisted',origin_frame=None,origin_position=None,
                         manual_engine='free' if from_zero else None,layers=[])
        if self.project_file and self.project_file.exists():
            loaded = json.loads(self.project_file.read_text(encoding='utf-8'))
            if loaded.get('hashes')!=self.hashes:
                raise ValueError('saved alignment belongs to a different recording/trajectory')
            self.data = loaded
            if from_zero and loaded.get('workflow')!='manual':
                raise ValueError('从零模式不能覆盖已有自动拼图项目，请选择新的项目文件')
        self.manual = self.data.get('workflow')=='manual'
        self.free_manual = self.manual and self.data.get('manual_engine')=='free'
        if self.manual:
            self.base[:] = 0
            self.accepted = [False]*len(self.ids)
        self.data.setdefault('masks',dict(outer_radius=self.settings.terrain_radius,center_radius=.32,global_shapes=[],frames={}))
        self.cache = OrderedDict();self.history = [];self.corrected = self.base.copy()
        self.residuals = [];self.iterations = 0;self.solve()
        self.migration_backup_pending = False
        if self.manual and not self.free_manual:
            # Preserve old manual graph results once; subsequent edits are free
            # layer placements and never pull neighbouring tiles around.
            active = set(self.selected_ids())|set(map(int,self.data['anchors']))
            active.update(p['a'] for p in self.data['pairs']);active.update(p['b'] for p in self.data['pairs'])
            self.data['anchors'] = {str(fid):self.pose(fid).tolist() for fid in active}
            self.data['manual_engine'] = 'free';self.free_manual = True;self.solve()
            self.migration_backup_pending = True
        self.data.setdefault('layers',self.selected_ids())

    def selected_ids(self):
        selected = [fid for fid,accepted in zip(self.ids,self.accepted) if self.data['included'].get(str(fid),accepted)]
        if self.manual:
            order = self.data.get('layers',[])
            return [fid for fid in order if fid in selected]+[fid for fid in selected if fid not in order]
        return selected

    def keyframes(self,distance=18,max_frames=180):
        selected = self.selected_ids();out = []
        for fid in selected:
            if not out or np.linalg.norm(self.pose(fid)-self.pose(out[-1]))>=distance or self.time(fid)-self.time(out[-1])>=8:
                out.append(fid)
        if selected and (not out or out[-1]!=selected[-1]):
            out.append(selected[-1])
        if len(out)>max_frames:
            out = [out[i] for i in np.unique(np.rint(np.linspace(0,len(out)-1,max_frames)).astype(int))]
        forced = set(map(int,self.data['anchors']))
        forced.update(p['a'] for p in self.data['pairs']);forced.update(p['b'] for p in self.data['pairs'])
        return sorted(set(out)|forced,key=self.lookup.__getitem__)

    def time(self,fid):
        return self.raw[self.lookup[fid]]['t']

    def pose(self,fid):
        return self.corrected[self.lookup[fid]].copy()

    def tile(self,fid):
        if fid not in self.lookup:
            raise ValueError('unknown frame')
        if fid not in self.cache:
            image = read_image(self.recording/'tiles'/f'{fid:06d}.png')
            self.cache[fid] = cv2.resize(image,(self.settings.tile_size,)*2)
            while len(self.cache)>32:
                self.cache.popitem(last=False)
        self.cache.move_to_end(fid)
        return self.cache[fid].copy()

    def _paint_shapes(self,mask,shapes):
        n = self.settings.tile_size
        for shape in shapes:
            if shape['kind']=='bitmap':
                encoded = shape['png']
                if len(encoded)>2_000_000:raise ValueError('mask bitmap is too large')
                image = cv2.imdecode(np.frombuffer(base64.b64decode(encoded,validate=True),np.uint8),cv2.IMREAD_GRAYSCALE)
                if image is None or image.shape!=(n,n):raise ValueError('mask dimensions differ')
                mask[:] = (image>127).astype(np.uint8)*255
                continue
            value = 0 if shape['op']=='erase' else 255
            points = np.rint(shape['points']).astype(np.int32)
            if shape['kind']=='polygon':
                cv2.fillPoly(mask,[points],value)
            elif shape['kind']=='brush':
                radius = max(1,round(shape['radius']))
                if len(points)>1:cv2.polylines(mask,[points],False,value,radius*2,lineType=cv2.LINE_8)
                for point in points:cv2.circle(mask,tuple(point),radius,value,-1)
        return mask

    def mask(self,fid=None,*,extra=None,scope='frame'):
        """White pixels contribute; global edits then per-frame overrides.

        Restoring never crosses the explicit outer/central circle boundaries.
        Those boundaries can themselves be enlarged/reduced by the user.
        """
        n = self.settings.tile_size;yy,xx = np.ogrid[:n,:n]
        cfg = self.data['masks']
        rr = ((xx-n/2)**2+(yy-n/2)**2)/(n/2)**2
        boundary = (rr<cfg['outer_radius']**2)&((rr>cfg['center_radius']**2) if cfg['center_radius'] else True)
        result = boundary.astype(np.uint8)*255
        global_shapes = cfg['global_shapes']+([extra] if extra and scope=='global' else [])
        self._paint_shapes(result,global_shapes)
        if fid is not None:
            self._paint_shapes(result,cfg['frames'].get(str(fid),[]))
            if extra and scope=='frame':self._paint_shapes(result,[extra])
        result[~boundary] = 0
        return result

    def set_circle(self,outer_pixels,center_pixels):
        n = self.settings.tile_size
        if not all(math.isfinite(v) for v in (outer_pixels,center_pixels)) or not 0<=center_pixels<outer_pixels<=n/2:
            raise ValueError(f'圆范围需满足：0 ≤ 中心半径 < 外圆半径 ≤ {n/2:g} 像素')
        self.remember();self.data['masks']['outer_radius'] = outer_pixels/(n/2)
        self.data['masks']['center_radius'] = center_pixels/(n/2);self.save()

    def _scope_shapes(self,scope,fid):
        if scope=='global':return self.data['masks']['global_shapes']
        if scope!='frame' or fid not in self.lookup:raise ValueError('invalid mask scope/frame')
        return self.data['masks']['frames'].setdefault(str(fid),[])

    def add_mask_shape(self,fid,shape,*,scope='frame'):
        n = self.settings.tile_size
        if shape.get('kind') not in ('brush','polygon') or shape.get('op') not in ('erase','restore'):
            raise ValueError('invalid mask drawing')
        points = shape.get('points',[])
        if not 1<=len(points)<=20000 or any(len(p)!=2 or not all(math.isfinite(v) and 0<=v<n for v in p) for p in points):
            raise ValueError('mask point outside tile')
        if shape['kind']=='polygon' and len(points)<3:raise ValueError('多边形至少需要三个点')
        if shape['kind']=='brush' and not 1<=shape.get('radius',0)<=n/2:raise ValueError('invalid brush radius')
        if scope not in ('global','frame') or fid not in self.lookup:raise ValueError('invalid mask scope')
        self.remember();self._scope_shapes(scope,fid).append(json.loads(json.dumps(shape)));self.save()

    def clear_mask(self,fid,*,scope='frame'):
        if scope not in ('global','frame') or fid not in self.lookup:raise ValueError('invalid mask scope')
        self.remember();self._scope_shapes(scope,fid).clear();self.save()

    def copy_frame_mask(self,source,destination):
        if source not in self.lookup or destination not in self.lookup:raise ValueError('invalid mask frame')
        self.remember()
        self.data['masks']['frames'][str(destination)] = json.loads(json.dumps(self.data['masks']['frames'].get(str(source),[])))
        self.save()

    def import_mask(self,fid,path,*,scope='frame'):
        image = cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)
        n = self.settings.tile_size
        if image is None or image.shape!=(n,n):raise ValueError(f'请使用 {n}×{n} 的黑白PNG掩膜：白色保留，黑色排除')
        if scope not in ('global','frame') or fid not in self.lookup:raise ValueError('invalid mask scope')
        shape = dict(kind='bitmap',png=base64.b64encode(cv2.imencode('.png',(image>127).astype(np.uint8)*255)[1]).decode('ascii'))
        self.remember();shapes = self._scope_shapes(scope,fid);shapes.clear();shapes.append(shape);self.save()

    def masked_landmarks(self):
        count = 0
        n = self.settings.tile_size
        for pair in self.data['pairs']:
            for fid,point in ((pair['a'],pair['pa']),(pair['b'],pair['pb'])):
                x,y = [min(n-1,round(v)) for v in point]
                count += not bool(self.mask(fid)[y,x])
        return count

    def remember(self):
        self.history.append(json.loads(json.dumps(self.data)))
        self.history = self.history[-40:]

    def undo(self):
        if self.history:
            self.data = self.history.pop();self.solve();self.save();return True
        return False

    def anchor(self,fid,position):
        if fid not in self.lookup or len(position)!=2 or not np.all(np.isfinite(position)):
            raise ValueError('invalid anchor')
        selected = self.selected_ids()
        origin = self.data.get('origin_frame') if self.manual else (selected[0] if selected else None)
        origin_position = np.asarray(self.data.get('origin_position') or (0,0)) if self.manual else self.base[self.lookup[selected[0]]] if selected else np.zeros(2)
        if not self.manual and fid==origin and np.linalg.norm(np.asarray(position)-origin_position)>1e-6:
            raise ValueError('首帧固定为坐标原点，请微调其他帧')
        self.remember();self.data['anchors'][str(fid)] = list(map(float,position))
        if not self.manual:self.data['included'][str(fid)] = True
        self.solve();self.save()

    def add_pair(self,a,point_a,b,point_b):
        if a==b or a not in self.lookup or b not in self.lookup:
            raise ValueError('choose two different frames')
        n = self.settings.tile_size
        for fid,point in ((a,point_a),(b,point_b)):
            if len(point)!=2 or not all(math.isfinite(v) and 0<=v<n for v in point):
                raise ValueError('landmark outside tile')
            if not self.mask(fid)[round(min(n-1,point[1])),round(min(n-1,point[0]))]:
                raise ValueError('请选择有效地形中的地标，避开中心角色和边框')
        self.remember()
        self.data['pairs'].append(dict(a=int(a),pa=list(map(float,point_a)),b=int(b),pb=list(map(float,point_b))))
        if self.free_manual:self.data['anchors'][str(b)] = (self.pose(a)+point_a-point_b).tolist()
        if not self.manual:
            self.data['included'][str(a)] = True;self.data['included'][str(b)] = True
        self.solve();self.save()

    def set_included(self,fid,enabled):
        if fid not in self.lookup:
            raise ValueError('unknown frame')
        if not self.manual and not enabled and any(fid in (p['a'],p['b']) for p in self.data['pairs']):
            raise ValueError('该帧有地标约束，请先删除相关约束')
        if not self.manual and not enabled and str(fid) in self.data['anchors']:
            raise ValueError('该帧已固定位置，请先删除固定约束')
        if not self.manual and not enabled and len(self.selected_ids())<=1:
            raise ValueError('至少保留一帧')
        position = self.pose(fid);was_included = fid in self.selected_ids()
        self.remember();self.data['included'][str(fid)] = bool(enabled)
        if self.manual:
            if enabled and not was_included:
                order = self.data.setdefault('layers',[])
                if fid in order:order.remove(fid)
                order.append(fid)
            selected = self.selected_ids()
            if not selected:
                self.data['origin_frame'] = None;self.data['origin_position'] = None
            elif self.data.get('origin_frame') not in selected:
                origin = fid if enabled else selected[0]
                self.data['origin_frame'] = origin
                self.data['origin_position'] = list(map(float,position if origin==fid else self.pose(origin)))
        self.solve();self.save()

    def remove_constraint(self,kind,key):
        self.remember()
        if kind=='anchor':
            self.data['anchors'].pop(str(key),None)
        elif kind=='pair':
            self.data['pairs'].pop(int(key))
        else:
            raise ValueError('unknown constraint type')
        self.solve();self.save()

    def solve(self):
        selected = self.selected_ids()
        self.corrected = self.base.copy();self.residuals = []
        if self.free_manual:
            for fid,position in self.data['anchors'].items():self.corrected[self.lookup[int(fid)]] = position
            for pair in self.data['pairs']:
                error = self.pose(pair['a'])+pair['pa']-self.pose(pair['b'])-pair['pb']
                self.residuals.append(float(np.linalg.norm(error)))
            self.iterations = 0;return
        if self.manual:
            draft_ids = set(selected)|set(map(int,self.data['anchors']))
            draft_ids.update(p['a'] for p in self.data['pairs']);draft_ids.update(p['b'] for p in self.data['pairs'])
            selected = sorted(draft_ids,key=self.lookup.__getitem__)
        if not selected:
            return
        local = {fid:i for i,fid in enumerate(selected)}
        edges = []
        for a,b in zip(selected,selected[1:]):
            dt = self.time(b)-self.time(a)
            edges.append((local[a],local[b],(0,0),1/max(.1,dt)))
        if self.manual:
            root = self.data.get('origin_frame')
            if root not in local:
                root = self.data['pairs'][0]['a'] if self.data['pairs'] else selected[0]
            position = self.data.get('origin_position')
            if position is None:position = self.data['anchors'].get(str(root),[0,0])
            anchors = [(local[root],np.asarray(position)-self.base[self.lookup[root]],1000)]
        else:anchors = [(0,(0,0),1000)]
        for key,position in self.data['anchors'].items():
            fid = int(key)
            if fid not in local:
                raise ValueError('anchor references excluded frame')
            anchors.append((local[fid],np.asarray(position)-self.base[self.lookup[fid]],1000))
        for pair in self.data['pairs']:
            a,b = pair['a'],pair['b']
            if a not in local or b not in local:
                raise ValueError('landmark references excluded frame')
            target = self.base[self.lookup[a]]+pair['pa']-self.base[self.lookup[b]]-pair['pb']
            edges.append((local[a],local[b],target,1000))
        correction,self.iterations = solve_graph(len(selected),edges,anchors)
        for fid,delta in zip(selected,correction):
            self.corrected[self.lookup[fid]] += delta
        for pair in self.data['pairs']:
            error = self.pose(pair['a'])+pair['pa']-self.pose(pair['b'])-pair['pb']
            self.residuals.append(float(np.linalg.norm(error)))

    def save(self):
        if self.project_file:
            if self.migration_backup_pending and self.project_file.exists():
                backup = self.project_file.with_name(self.project_file.stem+'.before-free.json')
                if not backup.exists():backup.write_bytes(self.project_file.read_bytes())
                self.migration_backup_pending = False
            atomic_json(self.project_file,self.data)

    def suggest_reference(self,fid):
        candidates = [v for v in self.selected_ids() if v!=fid]
        revisits = [v for v in candidates if abs(self.time(v)-self.time(fid))>5]
        candidates = revisits or candidates
        return min(candidates,key=lambda v:np.linalg.norm(self.pose(v)-self.pose(fid))) if candidates else fid

    def layer_order(self,fid,*,front=True):
        if not self.manual or fid not in self.selected_ids():raise ValueError('先将该帧加入手工拼图')
        self.remember();order = self.data.setdefault('layers',self.selected_ids())
        if fid in order:order.remove(fid)
        if front:order.append(fid)
        else:order.insert(0,fid)
        self.save()

    def _place(self,mapper,image,mask,integer):
        mapper._integrate(image,mask,integer)
        if self.manual:
            n = image.shape[0];ox,oy = mapper.origin
            x,y = round(integer[0]-n/2)-ox,round(integer[1]-n/2)-oy
            region = mapper.image[y:y+n,x:x+n];valid = mask>0
            region[valid] = image[valid]

    def preview(self,*,overrides=None):
        """Only explicitly included frames, no file writes or automatic registration."""
        mapper = MinimapMapper(self.settings);n = self.settings.tile_size
        for fid in self.selected_ids():
            position = np.asarray((overrides or {}).get(fid,self.pose(fid)));integer = np.rint(position);fraction = position-integer
            transform = np.float32([[1,0,fraction[0]],[0,1,fraction[1]]])
            image = cv2.warpAffine(self.tile(fid),transform,(n,n),flags=cv2.INTER_LINEAR)
            alpha = cv2.warpAffine(self.mask(fid).astype(np.float32)/255,transform,(n,n),flags=cv2.INTER_LINEAR)
            self._place(mapper,image,(alpha>.999).astype(np.uint8)*255,integer)
        self.preview_origin = mapper.origin
        return mapper.image

    def export(self,output,*,cancelled=lambda:False,progress=lambda done,total:None):
        """Compose corrected frames only; never rerun matching or alter source."""
        output = Path(output);output.mkdir(parents=True,exist_ok=False)
        atomic_json(output/'export-status.json',dict(completed=False,reason='in_progress'))
        selected = self.selected_ids()
        if not selected:
            raise ValueError('no frames selected')
        mapper = MinimapMapper(self.settings);n = self.settings.tile_size
        mapper.spec = replace(mapper.spec,inner_radius=self.data['masks']['outer_radius'],player_mask_radius=self.data['masks']['center_radius'])
        placements = []
        for count,fid in enumerate(selected,1):
            if cancelled():
                atomic_json(output/'export-status.json',dict(completed=False,reason='cancelled'))
                raise RuntimeError('导出已取消，源记录和修正项目已保留')
            image = self.tile(fid);mask = self.mask(fid);position = self.pose(fid);integer = np.rint(position)
            fraction = position-integer
            transform = np.float32([[1,0,fraction[0]],[0,1,fraction[1]]])
            shifted = cv2.warpAffine(image,transform,(n,n),flags=cv2.INTER_LINEAR)
            alpha = cv2.warpAffine(mask.astype(np.float32)/255,transform,(n,n),flags=cv2.INTER_LINEAR)
            valid = (alpha>.999).astype(np.uint8)*255
            self._place(mapper,shifted,valid,integer)
            mapper.position = position.copy();mapper.previous = image;mapper.previous_mask = mask
            mapper.trajectory.append(dict(t=self.time(fid),x=float(position[0]),y=float(position[1])))
            mapper.accepted += 1;mapper.tiles += 1
            if not mapper.keyframes or np.linalg.norm(position-mapper.keyframes[-1][2])>=self.settings.keyframe_distance:
                mapper.keyframes.append((image.copy(),mask.copy(),position.copy()))
                if len(mapper.keyframes)>self.settings.max_keyframes:
                    mapper.keyframes.pop(1)
            placements.append(dict(frame_id=fid,t=self.time(fid),x=float(position[0]),y=float(position[1]),accepted=True))
            if count%20==0 or count==len(selected):
                progress(count,len(selected))
        mapper.rejected = len(self.ids)-len(selected)
        mapper.last_result = MappingResult(True,'human_constrained_export',self.time(selected[-1]),*mapper.position)
        if mapper.weights is None or not np.any(mapper.weights):
            raise ValueError('所有参与帧的掩膜均为空，没有可导出的有效地图像素')
        report = mapper.save(output)
        write_image(output/'global-input-mask.png',self.mask())
        (output/'frame-masks').mkdir()
        for fid in self.data['masks']['frames']:
            write_image(output/'frame-masks'/f'{int(fid):06d}.png',self.mask(int(fid)))
        config = json.loads((output/'patrol-config.json').read_text(encoding='utf-8'))
        config['input_mask'] = 'global-input-mask.png'
        atomic_json(output/'patrol-config.json',config)
        atomic_json(output/'alignment.json',self.data)
        atomic_json(output/'corrected-placements.json',placements)
        atomic_json(output/'export-status.json',dict(completed=True,source=str(self.recording),
                    placement_source=str(self.placements),frames=len(selected),pairs=len(self.data['pairs']),
                    anchors=len(self.data['anchors']),landmark_residual_pixels=self.residuals,
                    max_correction_pixels=float(np.linalg.norm(self.corrected-self.base,axis=1).max()),
                    human_review_complete=False,entire_world_explored=False))
        return report
