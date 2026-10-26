"""Live observations anchored to an immutable, manually assembled minimap.

Candidate pixels are preview only. They never become localization evidence.
This deliberately stops at gaps without enough original reference overlap.
"""
from dataclasses import asdict
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .minimap_mapper import MinimapMapper, MappingResult, _photometric
from .patrol_vision import MinimapLocalizer, MinimapSpec, read_image, write_image


def crop_padded(image, center, n):
    left, top = np.rint(np.asarray(center)-n/2).astype(int)
    out = np.zeros((n,n)+image.shape[2:], image.dtype)
    h,w = image.shape[:2]
    x,y,r,b = max(0,left),max(0,top),min(w,left+n),min(h,top+n)
    if r>x and b>y:
        out[y-top:b-top,x-left:r-left] = image[y:b,x:r]
    return out, np.array((left,top))


def verify_reference(reference, patch, coverage, mask):
    """Bounded translation check against observed pixels in separate quadrants.

Manual layer seams need not share one affine feature transform. Require strong
photometric agreement plus texture in at least two spatially separate regions.
"""
    best = None
    for dy in range(-2,3):
        for dx in range(-2,3):
            score,overlap = _photometric(reference,patch,coverage,mask,(dx,dy))
            if overlap>=.6 and score>=.90 and (best is None or score>best['score']):
                best = dict(dx=float(dx),dy=float(dy),score=score,overlap=overlap,
                            inliers=0,method='fixed_reference_pixel_regions')
    if best is None:
        return None
    n = mask.shape[0];confirmed = 0
    for y,x in ((0,0),(0,n//2),(n//2,0),(n//2,n//2)):
        region = np.zeros_like(coverage)
        region[y:y+n//2,x:x+n//2] = coverage[y:y+n//2,x:x+n//2]
        valid = (region>0)&(mask>0)
        if valid.sum()<150 or np.std(reference[valid].astype(float),axis=0).max()<8:
            continue
        score,overlap = _photometric(reference,patch,region,mask,(best['dx'],best['dy']))
        confirmed += score>=.85
    return best if confirmed>=2 else None


class AnchoredMapper(MinimapMapper):
    def __init__(self, config_path, settings=None):
        path = Path(config_path).resolve()
        self.config = json.loads(path.read_text(encoding='utf-8-sig'))
        spec = MinimapSpec(**self.config.get('minimap',{}))
        super().__init__(settings, spec)
        self.source_config = path
        self.fixed = read_image(path.parent/self.config['reference'])
        if not self.config.get('coverage'):
            raise ValueError('reference continuation requires an explicit coverage mask')
        self.fixed_mask = read_image(path.parent/self.config['coverage'])[:,:,0]>127
        if self.fixed_mask.shape != self.fixed.shape[:2]:
            raise ValueError('reference coverage size differs')
        self.custom_mask = None
        if self.config.get('input_mask'):
            self.custom_mask = read_image(path.parent/self.config['input_mask'])[:,:,0]
        n = self.settings.tile_size
        self.locator = MinimapLocalizer(self.fixed,spec=self.spec,scales=(1.,),patch_size=n,
            analysis_scale=1.,min_score=.80,min_margin=.04,stable_frames=2,
            reference_mask=self.fixed_mask.astype(np.uint8)*255,input_mask=self.custom_mask,
            mask_reference_during_search=True,
            max_speed=180,jump_slack=8)
        self.image = self.fixed.copy()
        self.weights = self.fixed_mask.astype(np.uint16)
        self.quality = np.zeros(self.weights.shape,np.uint8)
        self.support = np.zeros_like(self.weights)
        self.candidates = np.zeros_like(self.image)
        self.last_sample = None
        self.origin = (0,0)  # This session uses pixels in the reference PNG.

    def add_tile(self,patch,mask,t,*,scene_valid=True):
        def reject(reason,diagnostic=None):
            self.rejected += 1
            self.last_result = MappingResult(False,reason,t,*self.position,
                score=diagnostic.score if diagnostic else 0)
            return self.last_result
        if not math.isfinite(t) or t<=self.last_t:
            return reject('stale_frame')
        self.last_t = t
        if not scene_valid:
            self.locator.previous = self.locator.pending = None
            self.locator.stable = 0
            return reject('scene_not_confirmed')
        if patch.ndim!=3 or patch.shape[:2]!=mask.shape or patch.shape[0]!=patch.shape[1]:
            raise ValueError('square tile and matching mask required')
        if self.patch_shape is None:
            self.patch_shape = patch.shape
        if patch.shape!=self.patch_shape:
            return reject('minimap_size_changed')
        if self.tiles>=self.settings.max_tiles:
            return reject('tile_budget')
        n = self.settings.tile_size
        patch = cv2.resize(patch,(n,n),interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask,(n,n),interpolation=cv2.INTER_NEAREST)
        yy,xx = np.ogrid[:n,:n]
        rr = ((xx-n/2)**2+(yy-n/2)**2)/(n/2)**2
        mask[(rr>=self.settings.terrain_radius**2)|(rr<=self.spec.player_mask_radius**2)] = 0
        if self.custom_mask is not None:
            mask[cv2.resize(self.custom_mask,(n,n),interpolation=cv2.INTER_NEAREST)<=127] = 0
        position = self.locator.match_patch(patch,mask,t)
        if not position.valid:
            return reject(position.reason,position)
        reference,corner = crop_padded(self.fixed,(position.x,position.y),n)
        coverage,_ = crop_padded(self.fixed_mask.astype(np.uint8)*255,(position.x,position.y),n)
        match = verify_reference(reference,patch,coverage,mask)
        if match is None:
            return reject('fixed_reference_geometry_unconfirmed')
        center = corner+n/2+np.array((match['dx'],match['dy']))
        self.position = center
        self.tiles += 1;self.accepted += 1
        self.trajectory.append(dict(t=t,x=float(center[0]),y=float(center[1])))
        new_pixels = 0
        if self.last_sample is None or np.linalg.norm(center-self.last_sample)>=4:
            integer = np.rint(center);fraction = center-integer
            transform = np.float32([[1,0,fraction[0]],[0,1,fraction[1]]])
            shifted = cv2.warpAffine(patch,transform,(n,n))
            valid = cv2.warpAffine(mask,transform,(n,n),flags=cv2.INTER_NEAREST)>0
            left,top = (integer-n/2).astype(int);h,w = self.fixed_mask.shape
            x,y,r,b = max(0,left),max(0,top),min(w,left+n),min(h,top+n)
            if r>x and b>y:
                sy,sx = y-top,x-left
                active = valid[sy:sy+b-y,sx:sx+r-x]&~self.fixed_mask[y:b,x:r]
                support = self.support[y:b,x:r]
                new_pixels = int(np.count_nonzero(active&(support==0)))
                support[active] = np.minimum(support[active].astype(np.uint32)+1,65535)
                self.candidates[y:b,x:r][active] = shifted[sy:sy+b-y,sx:sx+r-x][active]
                self.image[y:b,x:r][active] = self.candidates[y:b,x:r][active]
                self.weights[y:b,x:r][active] = 1
            self.last_sample = center.copy()
        self.last_result = MappingResult(True,'fixed_reference_candidate',t,*center,
            new_pixels=new_pixels,**match)
        return self.last_result

    def display(self,max_width=1000):
        canvas = super().display(max_width=100000)
        # Orange contour marks provisional additions, rather than implying final map.
        contours,_ = cv2.findContours((self.support>0).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas,contours,-1,(0,140,255),1)
        if self.last_result and not self.last_result.accepted:
            # The path's endpoint is historical, not a current tracking fix.
            x,y = np.rint(self.position).astype(int)
            cv2.circle(canvas,(x,y),14,(0,140,255),2)
            cv2.putText(canvas,'LOCATION LOST - last known position',(8,25),
                cv2.FONT_HERSHEY_SIMPLEX,.5,(0,140,255),1)
        if canvas.shape[1]>max_width:
            canvas = cv2.resize(canvas,(max_width,round(canvas.shape[0]*max_width/canvas.shape[1])))
        return canvas

    def save(self,output):
        output = Path(output);output.mkdir(parents=True,exist_ok=True)
        candidate = self.support>0
        rgba = cv2.cvtColor(self.candidates,cv2.COLOR_BGR2BGRA)
        rgba[:,:,3] = candidate.astype(np.uint8)*255
        write_image(output/'candidate-overlay.png',rgba)
        write_image(output/'candidate-coverage.png',candidate.astype(np.uint8)*255)
        write_image(output/'reference.png',self.fixed)
        write_image(output/'preview.png',self.display())
        report = dict(source_config=str(self.source_config),accepted=self.accepted,rejected=self.rejected,
            tiles=self.tiles,settings=asdict(self.settings),origin_world_xy=[0,0],
            coordinate_system='source reference PNG pixels',trajectory=self.trajectory,
            candidate_pixels=int(candidate.sum()),reference_unchanged=True,
            candidates_reviewed=False,entire_world_explored=False,live_verified=False)
        (output/'mapping.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
