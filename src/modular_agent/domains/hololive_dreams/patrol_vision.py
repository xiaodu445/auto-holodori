"""North-up minimap registration with explicit scale and ambiguity rejection.

Scores are template similarities, not probabilities. The supplied illustrated
drop map is a provisional reference; a clean full map is still required.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import cv2
import numpy as np

from .patrol import Position


def read_image(path):
    image = cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'cannot decode image: {path}')
    return image


def write_image(path,image):
    ok,data = cv2.imencode('.png',image)
    if not ok:
        raise ValueError('image encode failed')
    data.tofile(str(path))


def layout_features(image):
    # Keep colour layout, suppress texture, avoid dependence on tiny text/icons.
    lab = cv2.cvtColor(cv2.GaussianBlur(image,(5,5),0),cv2.COLOR_BGR2LAB).astype(np.float32)
    lab[:,:,0] *= .65
    return lab


def covered_match_scores(region,template,valid,coverage,minimum_overlap=.6):
    """Pearson correlation over the intersection of both observed masks.

    Unknown reference holes must not contribute black terrain to either mean
    or variance. OpenCV's template mask alone cannot express this intersection.
    """
    mask = (valid>0).astype(np.float32)
    known = (coverage>0).astype(np.float32)
    def correlate(a,b):
        return cv2.matchTemplate(np.ascontiguousarray(a,np.float32),
                                 np.ascontiguousarray(b,np.float32),cv2.TM_CCORR)
    count = correlate(known,mask)
    safe = np.maximum(count,1)
    covariance = np.zeros_like(count);va = np.zeros_like(count);vb = np.zeros_like(count)
    # Subtract a fixed offset for numerical conditioning; local means are still
    # computed independently per channel on exactly the observed intersection.
    for channel in range(region.shape[2]):
        a = (region[:,:,channel]-128)*known
        b = (template[:,:,channel]-128)*mask
        sa = correlate(a,mask);sb = correlate(known,b)
        covariance += correlate(a,b)-sa*sb/safe
        va += np.maximum(0,correlate(a*a,mask)-sa*sa/safe)
        vb += np.maximum(0,correlate(known,b*b)-sb*sb/safe)
    denominator = np.sqrt(va*vb)
    scores = covariance/np.maximum(denominator,1e-5)
    scores[(count<mask.sum()*minimum_overlap)|(va<safe*4)|(vb<safe*4)] = -1
    return np.clip(scores,-1,1)


@dataclass
class MinimapSpec:
    center_uv: tuple[float,float] = (143/1260,127/709)
    radius_width: float = 82/1260
    inner_radius: float = .94
    player_mask_radius: float = .28
    mask_dynamic_icons: bool = True

    def crop(self,frame,*,mask_icons=None):
        h,w = frame.shape[:2]
        cx,cy = round(self.center_uv[0]*w),round(self.center_uv[1]*h)
        radius = round(self.radius_width*w)
        if radius < 12 or not (0 <= cx-radius and cx+radius <= w and 0 <= cy-radius and cy+radius <= h):
            raise ValueError('minimap ROI outside frame')
        patch = frame[cy-radius:cy+radius,cx-radius:cx+radius].copy()
        yy,xx = np.ogrid[:2*radius,:2*radius]
        rr = ((xx-radius)**2+(yy-radius)**2)/radius**2
        mask = ((rr < self.inner_radius**2)&(rr > self.player_mask_radius**2)).astype(np.uint8)*255
        # Cyan POI/drop markers change between overview/minimap. Suppress them.
        hsv = cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
        icons = cv2.inRange(hsv,(80,65,70),(115,255,255))
        if self.mask_dynamic_icons if mask_icons is None else mask_icons:
            mask[cv2.dilate(icons,np.ones((5,5),np.uint8))>0] = 0
        return patch,mask


class MinimapLocalizer:
    def __init__(self,reference,*,scales=(1.0,1.25,1.5,1.75,2.0,2.25,2.5,3.0,3.5,4.0),
                 min_score=.65,min_margin=.035,max_speed=300.0,jump_slack=12.0,
                 stable_frames=2,spec=None,analysis_scale=.5,patch_size=None,reference_mask=None,input_mask=None,
                 mask_reference_during_search=False):
        if reference is None or reference.ndim != 3:
            raise ValueError('colour reference required')
        if not scales or any(not math.isfinite(s) or s <= 0 for s in scales):
            raise ValueError('invalid scales')
        if not (0 < min_score < 1 and 0 < min_margin < 1 and max_speed > 0 and jump_slack > 0 and stable_frames >= 1):
            raise ValueError('invalid localization settings')
        if not .1 <= analysis_scale <= 1:
            raise ValueError('invalid analysis scale')
        self.reference = reference
        if patch_size is not None and (type(patch_size) is not int or patch_size<24):
            raise ValueError('invalid normalized patch size')
        if reference_mask is not None and reference_mask.shape!=reference.shape[:2]:
            raise ValueError('reference coverage dimensions differ')
        self.patch_size = patch_size;self.reference_mask = reference_mask
        self.mask_reference_during_search = mask_reference_during_search
        if input_mask is not None and (input_mask.ndim!=2 or min(input_mask.shape)<1):
            raise ValueError('invalid input minimap mask')
        self.input_mask = input_mask
        self.analysis_scale = analysis_scale
        analysis = cv2.resize(reference,None,fx=analysis_scale,fy=analysis_scale)
        self.features = layout_features(analysis)
        self.analysis_coverage = (cv2.resize(reference_mask,(analysis.shape[1],analysis.shape[0]),
            interpolation=cv2.INTER_NEAREST) if reference_mask is not None else None)
        self.scales = tuple(scales);self.min_score = min_score;self.min_margin = min_margin
        self.max_speed = max_speed;self.jump_slack = jump_slack;self.stable_frames = stable_frames
        self.spec = spec or MinimapSpec()
        self.previous = None;self.pending = None;self.stable = 0;self.last_t = -math.inf

    def locate(self,frame,t):
        patch,mask = self.spec.crop(frame)
        return self.match_patch(patch,mask,t)

    def match_patch(self,patch,mask,t):
        if self.input_mask is not None:
            custom = cv2.resize(self.input_mask,(patch.shape[1],patch.shape[0]),interpolation=cv2.INTER_NEAREST)
            mask = cv2.bitwise_and(mask,(custom>127).astype(np.uint8)*255)
        if self.patch_size:
            patch = cv2.resize(patch,(self.patch_size,self.patch_size))
            mask = cv2.resize(mask,(self.patch_size,self.patch_size),interpolation=cv2.INTER_NEAREST)
        if not math.isfinite(t) or t <= self.last_t:
            return Position(0,0,t,False,reason='nonfresh_timestamp')
        self.last_t = t
        candidates = []
        h,w = self.features.shape[:2]
        factor = self.analysis_scale
        for scale in self.scales:
            tw,th = round(patch.shape[1]*scale*factor),round(patch.shape[0]*scale*factor)
            if tw < 12 or th < 12 or tw > w or th > h:
                continue
            template = cv2.resize(patch,(tw,th),interpolation=cv2.INTER_LINEAR)
            valid = cv2.resize(mask,(tw,th),interpolation=cv2.INTER_NEAREST)
            if np.count_nonzero(valid) < tw*th*.15:
                continue
            feature = layout_features(template)
            if float(np.std(feature[valid>0],axis=0).max()) < 2:
                continue
            # Temporal prior bounds tracking search, but the initial acquisition
            # still searches the complete map and rejects duplicate geometry.
            left,top,right,bottom = 0,0,w,h
            if self.previous and 0 < t-self.previous.t <= 2:
                reach = (self.jump_slack+self.max_speed*(t-self.previous.t))*factor
                px,py = self.previous.x*factor,self.previous.y*factor
                left = max(0,int(px-reach-tw/2))
                top = max(0,int(py-reach-th/2))
                right = min(w,math.ceil(px+reach+tw/2))
                bottom = min(h,math.ceil(py+reach+th/2))
            region = self.features[top:bottom,left:right]
            if region.shape[0] < th or region.shape[1] < tw:
                continue
            if self.mask_reference_during_search and self.analysis_coverage is not None:
                scores = covered_match_scores(region,feature,valid,self.analysis_coverage[top:bottom,left:right])
            else:
                scores = cv2.matchTemplate(region,feature,cv2.TM_CCOEFF_NORMED,mask=valid)
            scores = np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
            # Retain top two spatially distinct peaks at each scale. Cross-scale
            # duplicates are grouped below instead of falsely creating ambiguity.
            for _ in range(2):
                _,score,_,xy = cv2.minMaxLoc(scores)
                if score <= -1:
                    break
                x,y = xy;cx,cy = x+left+tw/2,y+top+th/2
                candidates.append((float(score),cx/factor,cy/factor,float(scale)))
                exclusion = max(12,round(min(tw,th)*.2))
                scores[max(0,y-exclusion):y+exclusion+1,max(0,x-exclusion):x+exclusion+1] = -1
        if not candidates:
            self.stable = 0;self.pending = None
            return Position(0,0,t,False,reason='insufficient_map_texture')
        candidates.sort(reverse=True)
        score,x,y,scale = candidates[0]
        exclusion = max(12,min(patch.shape[:2])*scale*.2)
        other = next((c[0] for c in candidates[1:] if math.hypot(c[1]-x,c[2]-y)>exclusion),-1.0)
        margin = score-other
        reason = ''
        if score < self.min_score:
            reason = 'low_similarity'
        elif margin < self.min_margin:
            reason = 'ambiguous_location'
        elif self.reference_mask is not None:
            tw,th = round(patch.shape[1]*scale),round(patch.shape[0]*scale)
            left,top = round(x-tw/2),round(y-th/2)
            coverage = self.reference_mask[max(0,top):max(0,top)+th,max(0,left):max(0,left)+tw]
            valid = cv2.resize(mask,(tw,th),interpolation=cv2.INTER_NEAREST)>0
            if coverage.shape!=valid.shape or np.mean(coverage[valid]>0)<.6:
                reason = 'insufficient_reference_coverage'
        if not reason and self.previous and math.hypot(x-self.previous.x,y-self.previous.y) > self.jump_slack+self.max_speed*(t-self.previous.t):
            reason = 'implausible_position_jump'
        if reason:
            self.stable = 0;self.pending = None
            return Position(x,y,t,False,score,margin,scale,reason)
        if self.pending and math.hypot(x-self.pending.x,y-self.pending.y) <= self.jump_slack+self.max_speed*(t-self.pending.t):
            self.stable += 1
        else:
            self.stable = 1
        result = Position(x,y,t,self.stable>=self.stable_frames,score,margin,scale,
                          '' if self.stable>=self.stable_frames else 'confirming_location')
        self.pending = result
        if result.valid:
            self.previous = result
        return result


class PickupPromptDetector:
    """Template + independent cyan enable colour in the same fresh ROI.

    Source templates are image #4's E key and 拾取 text. Two anchors prevent a
    generic blue action button from becoming an arbitrary E action.
    """
    def __init__(self,key_template,text_template,threshold=.88):
        self.key = key_template;self.text = text_template;self.threshold = threshold

    def read(self,frame):
        h,w = frame.shape[:2]
        # Normalize to the reference client size, not the window decoration.
        normalized = cv2.resize(frame,(1260,709))
        roi = normalized[390:490,760:1220]
        def score(template):
            gray = cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
            template = cv2.cvtColor(template,cv2.COLOR_BGR2GRAY)
            return cv2.minMaxLoc(cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED))[1]
        ks,ts = score(self.key),score(self.text)
        visible = ks >= self.threshold and ts >= self.threshold
        hsv = cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        cyan = float(np.mean(cv2.inRange(hsv,(80,65,100),(110,255,255))>0))
        return dict(visible=visible,enabled=visible and cyan>.15,key_score=ks,text_score=ts,cyan_fraction=cyan)


def drop_candidates(image):
    """Offline cyan marker centres, all unreviewed; POIs may be included."""
    hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    binary = cv2.inRange(hsv,(80,70,80),(105,255,255))
    count,labels,stats,centers = cv2.connectedComponentsWithStats(binary)
    result = []
    for i in range(1,count):
        x,y,w,h,area = stats[i]
        if 10 <= w <= 42 and 10 <= h <= 42 and .65 <= w/h <= 1.45 and area >= 80:
            cx,cy = centers[i]
            result.append(dict(x=round(float(cx),2),y=round(float(cy),2),reviewed=False))
    return sorted(result,key=lambda p:(p['y'],p['x']))
