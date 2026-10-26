"""Incremental, north-up minimap mapping without a pre-existing world map.

Only translations are admitted. Unknown pixels remain unknown, and registration
failure never advances dead-reckoned coordinates. All units are normalized
minimap pixels. No game input or native window dependencies live in this file.
"""
from __future__ import annotations

from dataclasses import dataclass,asdict,replace
import math
from pathlib import Path
import json

import cv2
import numpy as np

from .patrol_vision import MinimapSpec,write_image


@dataclass(frozen=True)
class MappingResult:
    accepted: bool
    reason: str
    t: float
    x: float = 0
    y: float = 0
    dx: float = 0
    dy: float = 0
    score: float = 0
    inliers: int = 0
    overlap: float = 0
    new_pixels: int = 0
    method: str = ''


@dataclass
class MapperSettings:
    tile_size: int = 164
    max_shift: float = 48
    min_inliers: int = 8
    min_overlap: float = .30
    min_similarity: float = .86
    max_residual: float = 1.5
    max_angle_degrees: float = 1.2
    max_scale_error: float = .015
    max_canvas_side: int = 4096
    max_tiles: int = 3000
    keyframe_distance: float = 18
    max_keyframes: int = 120
    terrain_radius: float = .78

    def __post_init__(self):
        for name,value in vars(self).items():
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(name)
        for name in ('tile_size','min_inliers','max_canvas_side','max_tiles','max_keyframes'):
            if type(getattr(self,name)) is not int:
                raise ValueError(name)
        if self.tile_size < 64 or self.max_shift >= self.tile_size*.5 or self.max_canvas_side < self.tile_size:
            raise ValueError('invalid tile/canvas/shift sizes')
        if not 0 < self.min_overlap <= 1 or not 0 < self.min_similarity <= 1:
            raise ValueError('invalid registration thresholds')
        if not .5 <= self.terrain_radius <= .94:
            raise ValueError('terrain radius includes decorative HUD')


def _gray(image):
    return cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)


def _photometric(previous,current,pmask,cmask,delta):
    h,w = previous.shape[:2]
    transform = np.float32([[1,0,delta[0]],[0,1,delta[1]]])
    moved = cv2.warpAffine(current,transform,(w,h),flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(cmask,transform,(w,h),flags=cv2.INTER_NEAREST)
    valid = cv2.erode(((valid>0)&(pmask>0)).astype(np.uint8),np.ones((3,3),np.uint8))>0
    overlap = float(np.count_nonzero(valid)/max(1,min(np.count_nonzero(pmask),np.count_nonzero(cmask))))
    if np.count_nonzero(valid)<100:
        return -1.,overlap
    a = cv2.GaussianBlur(previous,(3,3),0)[valid].astype(np.float32)
    b = cv2.GaussianBlur(moved,(3,3),0)[valid].astype(np.float32)
    a -= a.mean(axis=0);b -= b.mean(axis=0)
    denom = float(np.linalg.norm(a)*np.linalg.norm(b))
    return (float(np.clip(np.sum(a*b)/denom,-1,1)) if denom>1e-5 else -1.),overlap


def register_pixels(previous,current,pmask,cmask,s):
    """Joint-mask normalized correlation, with an explicit competing-peak veto.

    No artificial mask edges enter the similarity calculation. This can recover
    narrow but unique terrain when an overlay mask leaves too few spread corners.
    """
    radius=int(s.max_shift)
    a=_gray(previous).astype(np.float32)/255
    b=_gray(current).astype(np.float32)/255
    p=(pmask>0).astype(np.float32);q=(cmask>0).astype(np.float32)
    def corr(left,right):
        return cv2.matchTemplate(np.pad(left,radius),right,cv2.TM_CCORR)
    count=np.maximum(corr(p,q),0)
    divisor=np.maximum(count,1)
    sa=corr(a*p,q);sb=corr(p,b*q)
    variance_a=np.maximum(corr(a*a*p,q)-sa*sa/divisor,0)
    variance_b=np.maximum(corr(p,b*b*q)-sb*sb/divisor,0)
    denominator=np.sqrt(variance_a*variance_b)
    score=(corr(a*p,b*q)-sa*sb/divisor)/np.maximum(denominator,1e-8)
    yy,xx=np.mgrid[-radius:radius+1,-radius:radius+1]
    overlap=count/max(1,min(np.count_nonzero(p),np.count_nonzero(q)))
    valid=(overlap>=s.min_overlap)&(count>=100)&(denominator>.01)&(xx*xx+yy*yy<=s.max_shift**2)
    score=np.where(valid,np.clip(score,-1,1),-1)
    y,x=np.unravel_index(np.argmax(score),score.shape);peak=float(score[y,x])
    rivals=score[(xx-xx[y,x])**2+(yy-yy[y,x])**2>=36]
    if peak<max(.94,s.min_similarity) or rivals.size and peak-float(rivals.max())<.025:return None
    delta=[float(x-radius),float(y-radius)]
    for axis in (0,1):
        ix,iy=(x,y)
        if (axis==0 and 0<x<2*radius) or (axis==1 and 0<y<2*radius):
            left=score[iy,ix-1] if axis==0 else score[iy-1,ix]
            right=score[iy,ix+1] if axis==0 else score[iy+1,ix]
            curvature=left-2*peak+right
            if curvature<-.001:delta[axis]+=float(np.clip(.5*(left-right)/curvature,-.5,.5))
    if math.hypot(*delta)>s.max_shift:return None
    similarity,fraction=_photometric(previous,current,pmask,cmask,delta)
    if similarity<s.min_similarity or fraction<s.min_overlap:return None
    return dict(dx=delta[0],dy=delta[1],score=similarity,overlap=fraction,inliers=0,method='masked_pixels')


def register_tiles(previous,current,pmask,cmask,settings=None,*,global_match=False):
    """Sparse flow plus feature fallback, RANSAC geometry and masked pixels.

    Result delta maps current tile pixels into previous tile coordinates. A
    positive delta.x means the player moved right on the north-up map.
    """
    s = settings or MapperSettings()
    if previous.shape != current.shape or pmask.shape != previous.shape[:2] or cmask.shape != current.shape[:2]:
        raise ValueError('registration dimensions differ')
    prev,cur = _gray(previous),_gray(current)
    candidates = []
    if not global_match:
        points = cv2.goodFeaturesToTrack(prev,500,.005,4,mask=pmask,blockSize=5)
        if points is not None and len(points)>=s.min_inliers:
            tracked,status,_ = cv2.calcOpticalFlowPyrLK(prev,cur,points,None,winSize=(21,21),maxLevel=3)
            if tracked is not None:
                back,back_status,_ = cv2.calcOpticalFlowPyrLK(cur,prev,tracked,None,winSize=(21,21),maxLevel=3)
                if back is not None:
                    p,q = points.reshape(-1,2),tracked.reshape(-1,2)
                    valid = (status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back.reshape(-1,2)-p,axis=1)<.8)
                    xy = np.rint(q).astype(int)
                    inside = (xy[:,0]>=0)&(xy[:,0]<cur.shape[1])&(xy[:,1]>=0)&(xy[:,1]<cur.shape[0])
                    valid &= inside
                    indexes = np.flatnonzero(valid)
                    valid[indexes] &= cmask[xy[indexes,1],xy[indexes,0]]>0
                    candidates.append(('flow',p[valid],q[valid]))
    # Independent descriptors also allow rejoining a known keyframe after a
    # textureless patch or a dropped frame; no unconstrained image warping.
    sift = cv2.SIFT_create(nfeatures=1000,contrastThreshold=.012,edgeThreshold=12)
    kp,dp = sift.detectAndCompute(prev,pmask)
    kq,dq = sift.detectAndCompute(cur,cmask)
    if dp is not None and dq is not None and len(dq)>=2:
        matches = cv2.BFMatcher().knnMatch(dp,dq,k=2)
        good = [a for pair in matches if len(pair)==2 for a,b in [pair] if a.distance<.72*b.distance]
        # Enforce one-to-one descriptor matches.
        used = set();unique = []
        for match in sorted(good,key=lambda m:m.distance):
            if match.trainIdx not in used:
                unique.append(match);used.add(match.trainIdx)
        candidates.append(('features',np.float32([kp[m.queryIdx].pt for m in unique]),
                           np.float32([kq[m.trainIdx].pt for m in unique])))
    best = None
    for method,p,q in candidates:
        if len(p)<s.min_inliers:
            continue
        transform,inliers = cv2.estimateAffinePartial2D(q,p,method=cv2.RANSAC,ransacReprojThreshold=1.5,maxIters=1000,confidence=.995)
        if transform is None or inliers is None:
            continue
        good = inliers.ravel()>0
        if np.count_nonzero(good)<s.min_inliers or np.mean(good)<.55:
            continue
        scale = math.hypot(transform[0,0],transform[1,0])
        angle = abs(math.degrees(math.atan2(transform[1,0],transform[0,0])))
        if abs(scale-1)>s.max_scale_error or angle>s.max_angle_degrees:
            continue
        delta = np.median(p[good]-q[good],axis=0)
        error = np.linalg.norm(p[good]-q[good]-delta,axis=1)
        if np.median(error)>s.max_residual or math.hypot(*delta)>s.max_shift:
            continue
        # Features confined to one tiny icon cannot anchor the whole map.
        spread = np.ptp(p[good],axis=0)
        if min(spread)<previous.shape[0]*.12:
            continue
        similarity,overlap = _photometric(previous,current,pmask,cmask,delta)
        if overlap<s.min_overlap or similarity<s.min_similarity:
            continue
        result = dict(dx=float(delta[0]),dy=float(delta[1]),score=similarity,
                      overlap=overlap,inliers=int(np.count_nonzero(good)),method=method)
        if best is None or result['score']>best['score']:
            best = result
    if best:
        # A repeating road/grid can produce a convincing but non-unique shift.
        # Reject very strong alternate translations rather than writing an
        # arbitrary repeated copy of the terrain into the mosaic.
        for offset in (8,16,24,32):
            for ax,ay in ((offset,0),(-offset,0),(0,offset),(0,-offset)):
                dx,dy = best['dx']+ax,best['dy']+ay
                if math.hypot(dx,dy)>s.max_shift:
                    continue
                alternate,overlap = _photometric(previous,current,pmask,cmask,(dx,dy))
                if overlap>=s.min_overlap and alternate>=.985 and alternate>=best['score']-.005:
                    return None
    return best or register_pixels(previous,current,pmask,cmask,s)


class MinimapMapper:
    def __init__(self,settings=None,spec=None):
        self.settings = settings or MapperSettings()
        self.spec = replace(spec or MinimapSpec(),mask_dynamic_icons=False,
                            inner_radius=min((spec or MinimapSpec()).inner_radius,self.settings.terrain_radius),
                            player_mask_radius=max((spec or MinimapSpec()).player_mask_radius,.32))
        self.image = None;self.weights = None;self.quality = None;self.origin = (0,0)
        self.previous = None;self.previous_mask = None;self.position = np.zeros(2,dtype=float)
        self.last_t = -math.inf;self.keyframes = [];self.trajectory = [];self.tiles = 0
        self.accepted = 0;self.rejected = 0;self.last_result = None
        self.patch_shape = None;self.lost = False

    def observe(self,frame,t,*,scene_valid=True):
        # Map and live localization now share minimap glyphs. Static cyan POIs
        # are useful landmarks; unlike the overview matcher, do not erase them
        # or erase cyan rivers. The moving central player stays masked.
        patch,mask = self.spec.crop(frame,mask_icons=False)
        return self.add_tile(patch,mask,t,scene_valid=scene_valid)

    def add_tile(self,patch,mask,t,*,scene_valid=True):
        def reject(reason):
            self.rejected += 1
            result = MappingResult(False,reason,t,*self.position)
            self.last_result = result
            return result
        if not math.isfinite(t) or t<=self.last_t:
            return reject('stale_frame')
        self.last_t = t
        if not scene_valid:
            self.lost = True
            return reject('scene_not_confirmed')
        if patch.ndim!=3 or patch.shape[:2]!=mask.shape or patch.shape[0]!=patch.shape[1]:
            raise ValueError('square color tile and same-size mask required')
        if self.patch_shape is None:
            self.patch_shape = patch.shape
        if patch.shape!=self.patch_shape:
            self.lost = True
            return reject('minimap_size_changed')
        n = self.settings.tile_size
        patch = cv2.resize(patch,(n,n),interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask,(n,n),interpolation=cv2.INTER_NEAREST)
        yy,xx = np.ogrid[:n,:n]
        rr = ((xx-n/2)**2+(yy-n/2)**2)/(n/2)**2
        mask[(rr>=self.settings.terrain_radius**2)|(rr<=self.spec.player_mask_radius**2)] = 0
        if np.count_nonzero(mask)<n*n*.15 or np.std(_gray(patch)[mask>0])<4:
            self.lost = True
            return reject('insufficient_texture')
        if self.tiles>=self.settings.max_tiles:
            return reject('tile_budget')
        registration = dict(dx=0.,dy=0.,score=1.,inliers=0,overlap=1.,method='seed')
        position = self.position.copy()
        if self.previous is not None:
            registration = register_tiles(self.previous,patch,self.previous_mask,mask,self.settings)
            if registration:
                position += (registration['dx'],registration['dy'])
            else:
                # Bounded keyframe relocalization. Require agreement of distinct
                # spatial matches; repeated geometry must not merge distant areas.
                matches = []
                for image,valid,pose in self.keyframes[-12:]:
                    candidate = register_tiles(image,patch,valid,mask,self.settings,global_match=True)
                    if candidate:
                        matches.append((candidate,pose+np.array((candidate['dx'],candidate['dy']))))
                if not matches:
                    self.lost = True
                    return reject('registration_lost_return_to_last_area')
                matches.sort(key=lambda m:m[0]['score'],reverse=True)
                registration,position = matches[0]
                if any(np.linalg.norm(p-position)>6 for _,p in matches[1:]):
                    self.lost = True
                    return reject('ambiguous_keyframe_location')
                registration = dict(registration,method='keyframe_'+registration['method'])
        try:
            new_pixels = self._integrate(patch,mask,position)
        except ValueError:
            return reject('canvas_budget')
        self.position = position;self.previous = patch;self.previous_mask = mask
        self.tiles += 1;self.accepted += 1;self.lost = False
        self.trajectory.append(dict(t=t,x=float(position[0]),y=float(position[1])))
        if not self.keyframes or np.linalg.norm(position-self.keyframes[-1][2])>=self.settings.keyframe_distance:
            self.keyframes.append((patch.copy(),mask.copy(),position.copy()))
            if len(self.keyframes)>self.settings.max_keyframes:
                # Preserve the initial anchor; bounded recent keyframes follow.
                self.keyframes.pop(1)
        result = MappingResult(True,'seed' if self.tiles==1 else 'registered',t,
                               float(position[0]),float(position[1]),new_pixels=new_pixels,**registration)
        self.last_result = result
        return result

    def _integrate(self,patch,mask,position):
        n = patch.shape[0]
        left,top = round(position[0]-n/2),round(position[1]-n/2)
        if self.image is None:
            self.image = np.zeros_like(patch);self.weights = np.zeros((n,n),np.uint16)
            self.quality = np.zeros((n,n),np.uint8)
            self.origin = (left,top)
        ox,oy = self.origin;h,w = self.weights.shape
        nx,ny = min(ox,left),min(oy,top)
        right,bottom = max(ox+w,left+n),max(oy+h,top+n)
        if max(right-nx,bottom-ny)>self.settings.max_canvas_side:
            raise ValueError('canvas budget')
        if (nx,ny,right,bottom)!=(ox,oy,ox+w,oy+h):
            padding = ((oy-ny,bottom-oy-h),(ox-nx,right-ox-w))
            self.image = np.pad(self.image,(*padding,(0,0)))
            self.weights = np.pad(self.weights,padding)
            self.quality = np.pad(self.quality,padding)
            self.origin = (nx,ny)
        x,y = left-nx,top-ny
        region = self.image[y:y+n,x:x+n];weights = self.weights[y:y+n,x:x+n]
        quality = self.quality[y:y+n,x:x+n]
        valid = mask>0
        new_pixels = int(np.count_nonzero(valid&(weights==0)))
        # Prefer the most central unmasked observation. Averaging hundreds of
        # slightly misregistered glyphs made double icons and baked circular HUD
        # shading into terrain; select pixels instead of accumulating that blur.
        yy,xx = np.ogrid[:n,:n]
        radius = np.sqrt((xx-n/2)**2+(yy-n/2)**2)/(n/2)
        candidate = np.clip(250-radius*200,1,250).astype(np.uint8)
        # The minimap also paints a moving warm field-of-view/range overlay
        # inside the terrain disk. Among similarly central views, prefer the
        # less yellow observation (the overlay raises red / suppresses blue).
        # This preserves an observed pixel rather than inventing terrain colour.
        old_tint = region[:,:,2].astype(np.int16)*2-region[:,:,0].astype(np.int16)
        new_tint = patch[:,:,2].astype(np.int16)*2-patch[:,:,0].astype(np.int16)
        update = valid&((weights==0)|(candidate.astype(np.int16)>quality.astype(np.int16)+35)|
                       ((candidate.astype(np.int16)>=quality.astype(np.int16)-18)&(new_tint<old_tint)))
        region[update] = patch[update]
        quality[valid] = np.maximum(quality[valid],candidate[valid])
        weights[valid] = np.minimum(weights[valid].astype(np.uint32)+1,65535).astype(np.uint16)
        return new_pixels

    def display(self,max_width=1000):
        if self.image is None:
            return np.zeros((300,500,3),np.uint8)
        canvas = self.image.copy();canvas[self.weights==0] = (30,30,30)
        ox,oy = self.origin
        pts = np.array([[round(p['x']-ox),round(p['y']-oy)] for p in self.trajectory],np.int32)
        if len(pts)>1:
            cv2.polylines(canvas,[pts],False,(0,180,255),1)
        if len(pts):
            current = tuple(np.rint(self.position-np.array((ox,oy))).astype(int))
            cv2.drawMarker(canvas,current,(0,0,255),cv2.MARKER_CROSS,15,2)
        if canvas.shape[1]>max_width:
            canvas = cv2.resize(canvas,(max_width,round(canvas.shape[0]*max_width/canvas.shape[1])))
        return canvas

    def save(self,output):
        output = Path(output);output.mkdir(parents=True,exist_ok=True)
        report = dict(accepted=self.accepted,rejected=self.rejected,tiles=self.tiles,
                      map_version=3,composition='central_observed_pixels_with_warm_overlay_rejection',
                      origin_world_xy=list(self.origin),coordinate_system='normalized minimap pixels, north-up; initial player=(0,0)',
                      known_pixels=int(np.count_nonzero(self.weights)) if self.weights is not None else 0,
                      entire_world_explored=False,walkability_verified=False,live_verified=False,
                      settings=asdict(self.settings),trajectory=self.trajectory,
                      last_result=asdict(self.last_result) if self.last_result else None)
        if self.image is not None:
            coverage = (self.weights>0).astype(np.uint8)*255
            write_image(output/'map.png',self.image)
            write_image(output/'coverage.png',coverage)
            write_image(output/'preview.png',self.display())
            rgba = cv2.cvtColor(self.image,cv2.COLOR_BGR2BGRA);rgba[:,:,3] = coverage
            write_image(output/'map-transparent.png',rgba)
            # Keep resumable exact observations and weights; no pickle loading.
            images = np.stack([v[0] for v in self.keyframes])
            masks = np.stack([v[1] for v in self.keyframes])
            poses = np.stack([v[2] for v in self.keyframes])
            np.savez_compressed(output/'state.tmp.npz',image=self.image,weights=self.weights,
                                quality=self.quality,
                                keyframes=images,masks=masks,poses=poses,
                                previous=self.previous,previous_mask=self.previous_mask,position=self.position,
                                metadata=np.array(json.dumps(report)))
            (output/'state.tmp.npz').replace(output/'state.npz')
            config = dict(reference='map.png',reference_reviewed=False,
                          coverage='coverage.png',note='Incremental minimap map; unknown pixels are not walkable evidence.',
                          minimap=asdict(self.spec),localization=dict(scales=[.85,.925,1,1.075,1.15],
                          patch_size=self.settings.tile_size,analysis_scale=.75,min_score=.7,min_margin=.035,max_speed=180,jump_slack=8,stable_frames=2))
            (output/'patrol-config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
        (output/'mapping.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report

    @classmethod
    def resume(cls,folder,spec=None):
        folder = Path(folder)
        report = json.loads((folder/'mapping.json').read_text(encoding='utf-8'))
        mapper = cls(MapperSettings(**report['settings']),spec)
        with np.load(folder/'state.npz',allow_pickle=False) as state:
            if 'metadata' in state:
                report = json.loads(str(state['metadata']))
            mapper.image = state['image'];mapper.weights = state['weights']
            mapper.quality = state['quality'] if 'quality' in state else np.zeros_like(mapper.weights,dtype=np.uint8)
            mapper.previous = state['previous'];mapper.previous_mask = state['previous_mask']
            mapper.position = state['position']
            mapper.keyframes = [(i,m,p) for i,m,p in zip(state['keyframes'],state['masks'],state['poses'])]
        mapper.origin = tuple(report['origin_world_xy']);mapper.trajectory = report['trajectory']
        mapper.accepted = report['accepted'];mapper.rejected = report['rejected'];mapper.tiles = report['tiles']
        # The first resumed capture must register; its original window size is
        # established anew. Nothing is pasted merely at the saved player pose.
        return mapper


class FrontierExplorer:
    """Short-pulse exploration planner over known pixels, no raw input.

    It scores directions by unseen area and avoids failed directions locally.
    A measured WASD calibration is mandatory. This is not an obstacle detector:
    no displacement after bounded probes blocks that direction and eventually
    stops, rather than claiming a wall or a fully explored world.
    """
    def __init__(self,motion,*,pulse=.15,max_actions=500,max_no_progress=4):
        motion.validate()
        if not 0<pulse<=.3 or max_actions<1 or max_no_progress<1:
            raise ValueError('exploration budgets')
        self.motion = motion;self.pulse = pulse;self.max_actions = max_actions
        self.max_no_progress = max_no_progress;self.actions = 0;self.no_progress = 0
        self.pending = None;self.blocked = {};self.last_key = None
        self.return_targets = []

    def _choices(self,mapper,position):
        ox,oy = mapper.origin;h,w = mapper.weights.shape
        cell = tuple(np.rint(position/12).astype(int))
        avoid = self.blocked.get(cell,set())
        choices = []
        for key,vector in self.motion.vectors.items():
            if key in avoid:
                continue
            unit = np.asarray(vector)/np.linalg.norm(vector)
            frontier = position+unit*mapper.settings.tile_size*.45
            yy,xx = np.mgrid[-16:17:4,-16:17:4]
            xs = np.rint(frontier[0]-ox+xx).astype(int);ys = np.rint(frontier[1]-oy+yy).astype(int)
            inside = (xs>=0)&(xs<w)&(ys>=0)&(ys<h)
            known = np.zeros_like(inside)
            known[inside] = mapper.weights[ys[inside],xs[inside]]>0
            novelty = float(np.mean(~known))
            choices.append((novelty,key))
        return choices

    def _start_backtrack(self,mapper):
        # Follow recorded, actually traversed breadcrumbs to a previous branch,
        # not a straight line through unseen terrain or guessed walkable colours.
        rows = mapper.trajectory
        for index in range(len(rows)-2,max(-1,len(rows)-600),-1):
            row = rows[index];point = np.array((row['x'],row['y']))
            if np.linalg.norm(point-mapper.position)<20:
                continue
            options = self._choices(mapper,point)
            if not options or max(v for v,k in options)<.30:
                continue
            path = []
            last = mapper.position
            for item in reversed(rows[index:]):
                target = np.array((item['x'],item['y']))
                if np.linalg.norm(target-last)>=4:
                    path.append(target);last = target
            if path:
                self.return_targets = path
                self.no_progress = 0
                return True
        return False

    def _backtrack(self,mapper):
        from .patrol import Decision,PatrolSettings
        while self.return_targets and np.linalg.norm(self.return_targets[0]-mapper.position)<5:
            self.return_targets.pop(0)
        if not self.return_targets:
            return None
        target = self.return_targets[0]
        pulse = self.motion.pulse(target-mapper.position,PatrolSettings(max_pulse=self.pulse))
        if pulse is None:
            return Decision('stop','breadcrumb_cannot_reduce_error')
        keys,duration = pulse
        return Decision('move','backtrack_recorded_path_to_frontier',keys,duration,tuple(target))

    def propose(self,mapper,*,cancelled=False):
        from .patrol import Decision
        if cancelled:
            return Decision('stop','cancelled')
        if self.actions>=self.max_actions:
            return Decision('stop','exploration_action_budget')
        if mapper.lost or mapper.last_result is None or not mapper.last_result.accepted:
            return Decision('wait','mapping_unavailable')
        position = mapper.position
        if self.pending is not None:
            before,key = self.pending
            displacement = float(np.linalg.norm(position-before))
            if displacement<.8:
                self.no_progress += 1
                cell = tuple(np.rint(position/12).astype(int))
                self.blocked.setdefault(cell,set()).add(key)
            else:
                self.no_progress = 0
            self.pending = None
        if self.no_progress>=self.max_no_progress:
            if self.return_targets or not self._start_backtrack(mapper):
                return Decision('stop','no_displacement_manual_recovery')
        backtrack = self._backtrack(mapper)
        if backtrack:
            return backtrack
        choices = self._choices(mapper,position)
        if not choices or max(v for v,k in choices)<.2:
            if self._start_backtrack(mapper):
                return self._backtrack(mapper)
            return Decision('stop','no_reachable_frontier_world_completion_unknown')
        _,key = max((value+(.06 if key==self.last_key else 0),key) for value,key in choices)
        return Decision('move','explore_unseen_minimap_edge',(key,),self.pulse)

    def dispatched(self,mapper,decision):
        """Call only after actual successful input dispatch, not shadow proposals."""
        self.pending = (mapper.position.copy(),decision.keys[0]);self.last_key = decision.keys[0]
        self.actions += 1
