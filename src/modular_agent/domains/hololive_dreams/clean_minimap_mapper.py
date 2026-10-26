"""Overlay-aware first-pass mapping for new scenes; recordings remain raw."""
from dataclasses import replace
import json
import math
from pathlib import Path
import numpy as np
from .minimap_mapper import MinimapMapper,MapperSettings,MappingResult
from .minimap_cleanup import exclude_view_cone,exclude_random_markers
from .patrol_vision import write_image


class CleanMinimapMapper(MinimapMapper):
    def __init__(self,settings=None,spec=None):
        super().__init__(settings or MapperSettings(terrain_radius=.89),spec)
        self.cone = {};self.clean_mask = None;self.cone_rejected = 0

    def add_tile(self,patch,mask,t,*,scene_valid=True):
        if patch.ndim!=3 or patch.shape[:2]!=mask.shape or patch.shape[0]!=patch.shape[1]:
            raise ValueError('square color tile and same-size mask required')
        # Parent retains shape, temporal, scene, budget and registration checks.
        if not scene_valid or not math.isfinite(t) or t<=self.last_t:
            return super().add_tile(patch,mask,t,scene_valid=scene_valid)
        clean,self.cone = exclude_view_cone(patch,mask)
        if not self.cone['valid']:
            self.last_t = t;self.cone_rejected += 1;self.rejected += 1
            self.last_result = MappingResult(False,'cone_direction_unknown_no_write',t,*self.position)
            return self.last_result
        clean,self.cone['random_markers_excluded'] = exclude_random_markers(patch,clean)
        self.clean_mask = clean
        return super().add_tile(patch,clean,t,scene_valid=scene_valid)

    def save(self,output):
        report = super().save(output)
        report.update(overlay_policy='pointer_cone_and_random_marker_exclusion',cone_rejected=self.cone_rejected,
                      note='First-pass map; drift and remaining circular overlays require manual/graph review.')
        output = Path(output)
        if self.clean_mask is not None:write_image(output/'latest-clean-mask.png',self.clean_mask)
        (output/'mapping.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report
