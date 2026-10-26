"""Passive tracking against a completed map, independent of map reconstruction."""
from dataclasses import replace
import json
from pathlib import Path
import time
import cv2
import numpy as np

from .patrol import Position
from .patrol_vision import MinimapSpec, MinimapLocalizer, read_image
from .minimap_cleanup import exclude_view_cone, exclude_random_markers


class FastMinimapTracker:
    def __init__(self,config_path):
        path = Path(config_path).resolve()
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        self.reference = read_image(path.parent/config['reference'])
        self.spec = replace(MinimapSpec(**config.get('minimap',{})),mask_dynamic_icons=False,
                            inner_radius=.84,player_mask_radius=.32)
        coverage = read_image(path.parent/config['coverage'])[:,:,0] if config.get('coverage') else None
        custom = read_image(path.parent/config['input_mask'])[:,:,0] if config.get('input_mask') else None
        self.locator = MinimapLocalizer(self.reference,spec=self.spec,scales=(1.,),analysis_scale=.5,
            patch_size=164,min_score=.80,min_margin=.035,stable_frames=2,max_speed=180,jump_slack=8,
            reference_mask=coverage,input_mask=custom,mask_reference_during_search=True)
        self.last_t = -float('inf');self.timing = {};self.cone = {};self.last_valid = None

    def locate(self,frame,t,*,scene_valid=True):
        patch,mask = self.spec.crop(frame,mask_icons=False)
        return self.match_patch(patch,mask,t,scene_valid=scene_valid)

    def match_patch(self,patch,mask,t,*,scene_valid=True):
        started = time.perf_counter()
        self.timing = {}
        if not np.isfinite(t) or t<=self.last_t:
            return Position(0,0,t,False,reason='nonfresh_timestamp')
        self.last_t = t
        if not scene_valid:
            self.locator.previous = self.locator.pending = None;self.locator.stable = 0
            return Position(0,0,t,False,reason='scene_not_confirmed')
        patch = cv2.resize(patch,(164,164),interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask,(164,164),interpolation=cv2.INTER_NEAREST)
        yy,xx = np.ogrid[:164,:164];rr = ((xx-82)**2+(yy-82)**2)/82**2
        mask[(rr>=.84**2)|(rr<=.32**2)] = 0
        clean,self.cone = exclude_view_cone(patch,mask)
        # This class never writes terrain. Unknown cone orientation can lower
        # similarity, but does not veto an otherwise strong map position fix.
        if self.cone['valid']:mask = clean
        mask,count = exclude_random_markers(patch,mask)
        self.cone['random_markers_excluded'] = count
        prepared = time.perf_counter()
        position = self.locator.match_patch(patch,mask,t)
        ended = time.perf_counter()
        self.timing = dict(mask_ms=(prepared-started)*1000,localization_ms=(ended-prepared)*1000,
                           tracking_ms=(ended-started)*1000,cone_known=self.cone['valid'])
        if position.valid:self.last_valid = position
        return position
