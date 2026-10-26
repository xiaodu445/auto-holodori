"""OFFLINE CROP SIMULATION only: exercise registration, not live game mapping."""
from pathlib import Path
import json
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import MinimapMapper
from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image
from modular_agent.realtime.patrol import ROOT,DATA,save_json


def main():
    cv2.setNumThreads(1)
    output = ROOT/'runtime/patrol/mapping-demo'
    (output/'tiles').mkdir(parents=True,exist_ok=True)
    source = read_image(DATA/'references/drop-map.png')
    path = ([(x,300) for x in range(300,501,8)]+
            [(500,y) for y in range(308,501,8)]+
            [(x,500) for x in range(492,299,-8)]+
            [(300,y) for y in range(492,299,-8)])
    mapper = MinimapMapper()
    n = 164;yy,xx = np.ogrid[:n,:n];rr = ((xx-82)**2+(yy-82)**2)/82**2
    mask = ((rr<.94**2)&(rr>.28**2)).astype(np.uint8)*255
    errors = [];timings = [];rows = []
    for i,(x,y) in enumerate(path):
        patch = source[y-82:y+82,x-82:x+82].copy()
        cv2.circle(patch,(82,82),14,(0,0,255),-1)
        write_image(output/'tiles'/f'{i:04d}.png',patch)
        start = time.perf_counter();result = mapper.add_tile(patch,mask,i*.25)
        timings.append((time.perf_counter()-start)*1000)
        if result.accepted:
            errors.append(float(np.linalg.norm(mapper.position-(x-300,y-300))))
        rows.append(dict(frame=i,accepted=result.accepted,reason=result.reason,score=result.score))
    mapper.save(output/'stitched')
    report = dict(kind='OFFLINE CROP SIMULATION, NOT LIVE GAME FOOTAGE',source='supplied annotated drop-map.png',
                  frames=len(path),accepted=mapper.accepted,rejected=mapper.rejected,
                  max_position_error_pixels=max(errors) if errors else None,
                  median_processing_ms=float(np.median(timings)),entire_world_explored=False,
                  sends_input=False,rows=rows)
    save_json(output/'demo-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))


if __name__=='__main__':
    main()
