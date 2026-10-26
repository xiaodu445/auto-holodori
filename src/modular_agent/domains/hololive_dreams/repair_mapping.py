"""Bounded translation pose graph with manual soft priors and cone-free tiles.

The graph retains source observations: changing poses rebuilds the image, so
old incorrectly placed pixels are removed rather than blended with corrections.
"""
from dataclasses import asdict, replace
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .anchored_mapping import AnchoredMapper, crop_padded
from .minimap_mapper import MappingResult, register_tiles
from .minimap_cleanup import exclude_view_cone, exclude_random_markers
from .patrol_vision import write_image, covered_match_scores


def match_near_prior(previous,current,pmask,cmask,prior,radius=6):
    """Pixel fallback for clean but sparse terrain, only near an existing pose.

    Distinct local peak, substantial observed overlap and both directional
    variances are required. Never used for unconstrained global acquisition.
    """
    n = current.shape[0]
    reference,corner = crop_padded(previous,np.asarray(prior)+n/2,n+2*radius)
    coverage,_ = crop_padded(pmask,np.asarray(prior)+n/2,n+2*radius)
    scores = covered_match_scores(cv2.GaussianBlur(reference,(3,3),0).astype(np.float32),
        cv2.GaussianBlur(current,(3,3),0).astype(np.float32),cmask,coverage,minimum_overlap=.35)
    _,score,_,point = cv2.minMaxLoc(scores)
    if score<.96:return None
    x,y = point;remaining = scores.copy()
    remaining[max(0,y-3):y+4,max(0,x-3):x+4] = -1
    if score-float(remaining.max())<.01:return None
    delta = corner+np.asarray(point)
    return dict(dx=float(delta[0]),dy=float(delta[1]),score=float(score),
                inliers=0,overlap=.35,method='bounded_clean_pixel_match')


def optimize_translations(base, edges, manual_count, iterations=4):
    """Robust translation constraints; manual positions are soft, first is gauge."""
    from modular_agent.realtime.minimap_alignment import solve_graph
    base = np.asarray(base,float)
    if not edges:
        return base.copy(),[]
    weights = np.array([edge[3] for edge in edges],float)
    correction = np.zeros_like(base)
    for _ in range(iterations):
        rows = [(i,j,np.asarray(delta)-(base[j]-base[i]),float(weight))
                for (i,j,delta,_),weight in zip(edges,weights)]
        anchors = [(i,(0.,0.),.08 if i<manual_count else .0001) for i in range(len(base))]
        anchors.append((0,(0.,0.),10000.))
        correction,_ = solve_graph(len(base),rows,anchors)
        residual = np.array([np.linalg.norm((base[j]+correction[j])-(base[i]+correction[i])-delta)
                             for i,j,delta,_ in edges])
        weights = np.array([edge[3] for edge in edges])*np.minimum(1.,2/np.maximum(residual,1e-6))
    return base+correction,residual.tolist()


def consensus_colors(samples,valid,fallback):
    """Choose a real observed color nearest the multi-view median, no averaging.

    Thin moving screen-space rings become outliers as their radius changes.
    Two-view disagreements retain the central-source fallback for review.
    """
    import warnings
    values = samples.astype(np.float32)
    values[~valid] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        median = np.nanmedian(values,axis=0)
    distance = np.sum(np.abs(values-median),axis=3)
    distance[~valid] = np.inf
    index = np.argmin(distance,axis=0)
    yy,xx = np.indices(index.shape)
    chosen = samples[index,yy,xx]
    result = fallback.copy();confirmed = valid.sum(axis=0)>=3
    result[confirmed] = chosen[confirmed]
    return result,confirmed


class RepairMapper(AnchoredMapper):
    def __init__(self,config_path,settings=None):
        super().__init__(config_path,settings)
        from modular_agent.realtime.minimap_alignment import AlignmentProject
        source = self.source_config.parent
        if not (source/'alignment.json').exists():
            raise ValueError('repair mode requires a manual export with alignment.json and raw source tiles')
        data = json.loads((source/'alignment.json').read_text(encoding='utf-8'))
        project = AlignmentProject(data['recording'],data['placements'],source/'alignment.json')
        manual = json.loads((source/'corrected-placements.json').read_text(encoding='utf-8'))
        origin = np.asarray(json.loads((source/'mapping.json').read_text(encoding='utf-8'))['origin_world_xy'])
        self.nodes = [];self.edges = [];self.repair_diagnostics = {};self.cone = {}
        self.settings = replace(self.settings,terrain_radius=min(.89,project.data['masks']['outer_radius']))
        self.spec = replace(self.spec,inner_radius=self.settings.terrain_radius)
        self.max_nodes = min(600,self.settings.max_tiles+len(manual))
        self.track_index = None;self.track_stamp = -float('inf')
        self.graph_dirty = False;self.last_optimize = 0.;self.residuals = []
        self.cone_rejected = 0;self.loop_edges = 0
        self.last_render = -float('inf')
        for row in manual:
            patch = project.tile(row['frame_id'])
            mask,cone = exclude_view_cone(patch,project.mask(row['frame_id']))
            if not cone['valid']:
                continue
            mask,cone['random_markers_excluded'] = exclude_random_markers(patch,mask)
            position = np.array((row['x'],row['y']))-origin
            self.nodes.append(dict(image=patch,mask=mask,base=position,pose=position.copy(),
                source=dict(kind='manual',frame_id=row['frame_id'],recording=str(project.recording)),cone=cone,t=-100.))
        if len(self.nodes)<2:
            raise ValueError('not enough manual tiles with recognizable player pointers')
        self.manual_count = len(self.nodes)
        # Independent manual layers get constraints only from actual overlap.
        for j,node in enumerate(self.nodes):
            self._connect(j,range(j),limit=8)
        self._optimize(force=True)
        self._render()

    def _connect(self,j,indexes,limit=8):
        node = self.nodes[j];matches = []
        for i in indexes:
            distance = np.linalg.norm(self.nodes[i]['pose']-node['pose'])
            if 4<distance<65:
                matches.append((distance,i))
        added = 0
        for _,i in sorted(matches)[:limit]:
            other = self.nodes[i]
            match = register_tiles(other['image'],node['image'],other['mask'],node['mask'],
                replace(self.settings,max_shift=70,min_overlap=.30,min_similarity=.93),global_match=True)
            if match is None:
                match = match_near_prior(other['image'],node['image'],other['mask'],node['mask'],node['pose']-other['pose'])
            if match is None:
                continue
            delta = np.array((match['dx'],match['dy']))
            if np.linalg.norm(delta-(node['pose']-other['pose']))>12:
                continue
            self.edges.append((i,j,delta,2.));added += 1
        self.graph_dirty |= added>0
        return added

    def _optimize(self,force=False):
        if not self.graph_dirty and not force:
            return
        if not force and time.perf_counter()-self.last_optimize<2:
            return
        base = np.array([n['base'] for n in self.nodes])
        poses,residuals = optimize_translations(base,self.edges,self.manual_count)
        movement = np.linalg.norm(poses-base,axis=1)
        # A graph that wants to rearrange geography is not silently accepted.
        if np.max(movement[:self.manual_count],initial=0)>12:
            self.repair_diagnostics['optimization_rejected'] = 'manual_shift_exceeds_12px'
        else:
            for node,pose in zip(self.nodes,poses):node['pose'] = pose
            self.residuals = residuals
            self.repair_diagnostics.pop('optimization_rejected',None)
        self.graph_dirty = False;self.last_optimize = time.perf_counter()

    def add_tile(self,patch,mask,t,*,scene_valid=True):
        def reject(reason):
            self.rejected += 1
            self.last_result = MappingResult(False,reason,t,*self.position)
            return self.last_result
        if not np.isfinite(t) or t<=self.last_t:return reject('stale_frame')
        self.last_t = t
        if not scene_valid:
            self.track_index = None
            self.locator.previous = self.locator.pending = None;self.locator.stable = 0
            return reject('scene_not_confirmed')
        if patch.ndim!=3 or patch.shape[:2]!=mask.shape or patch.shape[0]!=patch.shape[1]:
            raise ValueError('square tile and matching mask required')
        if self.patch_shape is None:self.patch_shape = patch.shape
        if patch.shape!=self.patch_shape:return reject('minimap_size_changed')
        if len(self.nodes)>=self.max_nodes or self.tiles>=self.settings.max_tiles:return reject('tile_budget')
        n = self.settings.tile_size
        patch = cv2.resize(patch,(n,n),interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask,(n,n),interpolation=cv2.INTER_NEAREST)
        yy,xx = np.ogrid[:n,:n];rr = ((xx-n/2)**2+(yy-n/2)**2)/(n/2)**2
        mask[(rr>=self.settings.terrain_radius**2)|(rr<=.32**2)] = 0
        if self.custom_mask is not None:
            mask[cv2.resize(self.custom_mask,(n,n),interpolation=cv2.INTER_NEAREST)<=127] = 0
        mask,self.cone = exclude_view_cone(patch,mask)
        if not self.cone['valid']:
            self.cone_rejected += 1
            return reject('cone_direction_unknown_no_write')
        mask,self.cone['random_markers_excluded'] = exclude_random_markers(patch,mask)
        previous = self.track_index;match = None;position = None
        if previous is not None and 0<t-self.track_stamp<2:
            old = self.nodes[previous]
            match = register_tiles(old['image'],patch,old['mask'],mask,
                replace(self.settings,max_shift=65,min_similarity=.94),global_match=False)
            if match:
                position = old['pose']+np.array((match['dx'],match['dy']))
        if position is None:
            # Global reference only acquires a coarse place; raw manual or live
            # overlap must independently confirm it before it enters the graph.
            self.locator.previous = None
            located = self.locator.match_patch(patch,mask,t)
            if not located.valid:return reject(located.reason)
            position = np.array((located.x,located.y))
        if previous is not None and match and np.linalg.norm(position-self.nodes[previous]['pose'])<6:
            old_heading = self.nodes[previous]['cone']['heading_degrees']
            turn = abs((self.cone['heading_degrees']-old_heading+180)%360-180)
            if turn<35:
                self.position = position;self.track_stamp = t
                self.accepted += 1;self.tiles += 1
                self.last_result = MappingResult(True,'tracked_no_new_keyframe',t,*position,**match)
                return self.last_result
        j = len(self.nodes)
        node = dict(image=patch.copy(),mask=mask.copy(),base=position.copy(),pose=position.copy(),
            source=dict(kind='live',t=t),cone=dict(self.cone),t=t)
        self.nodes.append(node)
        added = self._connect(j,(i for i in range(j) if i!=previous),limit=10)
        if match and previous is not None:
            self.edges.append((previous,j,np.array((match['dx'],match['dy'])),4.));self.graph_dirty = True
        elif not added:
            self.nodes.pop()
            return reject('raw_overlap_unconfirmed')
        self.loop_edges += added
        self._optimize()
        self.position = self.nodes[j]['pose'].copy()
        self.track_index = j;self.track_stamp = t
        self.tiles += 1;self.accepted += 1
        self.trajectory.append(dict(t=t,x=float(self.position[0]),y=float(self.position[1]),node=j))
        before = int(np.count_nonzero(self.weights))
        if time.perf_counter()-self.last_render>=3:
            self._render(consensus=True)
            self.last_render = time.perf_counter()
        self.last_result = MappingResult(True,'cone_free_graph_keyframe',t,*self.position,
            score=match['score'] if match else 1.,new_pixels=max(0,int(np.count_nonzero(self.weights))-before),
            method='translation_pose_graph')
        return self.last_result

    def _render(self,consensus=False):
        h,w = self.fixed_mask.shape
        # Rebuild from source tiles, never from a previously blended map.
        image = np.zeros_like(self.fixed);rank = np.full((h,w),np.inf,np.float32)
        support = np.zeros((h,w),np.uint16);owner = np.full((h,w),-1,np.int32)
        n = self.settings.tile_size;yy,xx = np.ogrid[:n,:n]
        radial = np.hypot(xx-n/2,yy-n/2)/(n/2)
        warped = []
        for index,node in enumerate(self.nodes):
            position = node['pose'];integer = np.rint(position);fraction = position-integer
            transform = np.float32([[1,0,fraction[0]],[0,1,fraction[1]]])
            patch = cv2.warpAffine(node['image'],transform,(n,n))
            mask = cv2.warpAffine(node['mask'],transform,(n,n),flags=cv2.INTER_NEAREST)>0
            left,top = (integer-n/2).astype(int);x,y,r,b = max(0,left),max(0,top),min(w,left+n),min(h,top+n)
            if r<=x or b<=y:continue
            sy,sx = y-top,x-left
            valid = mask[sy:sy+b-y,sx:sx+r-x]
            quality = radial[sy:sy+b-y,sx:sx+r-x]
            region = rank[y:b,x:r];update = valid&(quality<region)
            image[y:b,x:r][update] = patch[sy:sy+b-y,sx:sx+r-x][update]
            region[update] = quality[update];owner[y:b,x:r][update] = index
            counts = support[y:b,x:r];counts[valid] += 1
            if consensus:
                warped.append((x,y,r,b,patch[sy:sy+b-y,sx:sx+r-x],valid))
        confirmed = np.zeros((h,w),bool)
        if consensus:
            for top in range(0,h,96):
                for left in range(0,w,96):
                    bottom,right = min(h,top+96),min(w,left+96)
                    samples = [];masks = []
                    for x,y,r,b,patch,valid in warped:
                        ax,ay,ar,ab = max(left,x),max(top,y),min(right,r),min(bottom,b)
                        if ar<=ax or ab<=ay:continue
                        sample = np.zeros((bottom-top,right-left,3),np.uint8)
                        mask = np.zeros(sample.shape[:2],bool)
                        sample[ay-top:ab-top,ax-left:ar-left] = patch[ay-y:ab-y,ax-x:ar-x]
                        mask[ay-top:ab-top,ax-left:ar-left] = valid[ay-y:ab-y,ax-x:ar-x]
                        samples.append(sample);masks.append(mask)
                    if len(samples)>=3:
                        image[top:bottom,left:right],confirmed[top:bottom,left:right] = consensus_colors(
                            np.stack(samples),np.stack(masks),image[top:bottom,left:right])
        self.image = image;self.support = support;self.owner = owner
        self.consensus_confirmed = confirmed
        self.weights = (support>0).astype(np.uint16)

    def display(self,max_width=1000):
        from .minimap_mapper import MinimapMapper
        canvas = MinimapMapper.display(self,max_width)
        if self.last_result and not self.last_result.accepted:
            cv2.putText(canvas,'LOCATION LOST - no map insertion',(8,25),
                cv2.FONT_HERSHEY_SIMPLEX,.5,(0,140,255),1)
        return canvas

    def save(self,output):
        self._optimize(force=True);self._render(consensus=True)
        output = Path(output);output.mkdir(parents=True,exist_ok=True)
        coverage = (self.support>0).astype(np.uint8)*255
        write_image(output/'repair-map.png',self.image)
        write_image(output/'repair-coverage.png',coverage)
        write_image(output/'multi-view-coverage.png',self.consensus_confirmed.astype(np.uint8)*255)
        rgba = cv2.cvtColor(self.image,cv2.COLOR_BGR2BGRA);rgba[:,:,3] = coverage
        write_image(output/'repair-map-transparent.png',rgba)
        write_image(output/'preview.png',self.display())
        changed = (self.support>0)&self.fixed_mask&(np.max(np.abs(self.image.astype(int)-self.fixed.astype(int)),axis=2)>20)
        write_image(output/'changed-pixels.png',changed.astype(np.uint8)*255)
        if self.track_index is not None:
            write_image(output/'latest-clean-mask.png',self.nodes[self.track_index]['mask'])
        graph = dict(nodes=[dict(source=n['source'],base=n['base'].tolist(),pose=n['pose'].tolist(),cone=n['cone']) for n in self.nodes],
            edges=[dict(a=i,b=j,delta=np.asarray(d).tolist(),weight=w) for i,j,d,w in self.edges],residuals=self.residuals)
        (output/'pose-graph.json').write_text(json.dumps(graph,indent=2),encoding='utf-8')
        report = dict(source_config=str(self.source_config),mode='cone_free_translation_pose_graph',
            accepted=self.accepted,rejected=self.rejected,tiles=self.tiles,keyframes=len(self.nodes),
            manual_nodes=self.manual_count,edges=len(self.edges),live_overlap_edges=self.loop_edges,
            cone_rejected=self.cone_rejected,settings=asdict(self.settings),origin_world_xy=[0,0],
            known_pixels=int(np.count_nonzero(self.support)),trajectory=self.trajectory,
            multi_view_pixels=int(np.count_nonzero(self.consensus_confirmed)),
            manual_max_shift=float(max(np.linalg.norm(n['pose']-n['base']) for n in self.nodes[:self.manual_count])),
            edge_residual_p95=float(np.percentile(self.residuals,95)) if self.residuals else None,
            diagnostics=self.repair_diagnostics,reviewed=False,live_verified=False,entire_world_explored=False)
        initial_residuals = [float(np.linalg.norm((self.nodes[j]['base']-self.nodes[i]['base'])-delta))
                             for i,j,delta,_ in self.edges]
        report['edge_residual_before_p95'] = float(np.percentile(initial_residuals,95)) if initial_residuals else None
        (output/'mapping.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        config = dict(self.config,reference='repair-map.png',coverage='repair-coverage.png',reference_reviewed=False)
        if self.custom_mask is not None:
            write_image(output/'global-input-mask.png',self.custom_mask)
            config['input_mask'] = 'global-input-mask.png'
        (output/'patrol-config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
        return report
