"""Reproducible diagnostics on the four supplied images, no game input."""
import json
from pathlib import Path
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image
from modular_agent.realtime.patrol import make_vision,overlay,save_json


def main():
    root = Path(__file__).resolve().parents[1]
    data = root/'domains/hololive_dreams/data/patrol'
    output = root/'runtime/patrol/reference-check'
    output.mkdir(parents=True,exist_ok=True)
    config = json.loads((data/'config.json').read_text(encoding='utf-8'))
    cv2.setNumThreads(1)
    rows = []
    for name in ('free-world','pickup'):
        reference,loc,det = make_vision(config,data/'config.json')
        frame = read_image(data/f'references/{name}.png')[38:,:1260]
        start = time.perf_counter()
        p = loc.locate(frame,0)
        elapsed = (time.perf_counter()-start)*1000
        pickup = det.read(frame)
        canvas = overlay(reference,p,label=name+' STATIC CANDIDATE')
        patch,mask = loc.spec.crop(frame)
        write_image(output/f'{name}-map.png',canvas)
        write_image(output/f'{name}-minimap.png',patch)
        write_image(output/f'{name}-mask.png',mask)
        # Timing only: replaying the same still cannot establish temporal accuracy.
        timings = []
        for i in range(1,9):
            tick = time.perf_counter();loc.locate(frame,i*.3)
            timings.append((time.perf_counter()-tick)*1000)
        rows.append(dict(source=name,candidate=dict(x=p.x,y=p.y,scale=p.scale,
                         score=p.score,margin=p.margin,valid=p.valid,reason=p.reason),
                         pickup=pickup,first_search_ms=elapsed,
                         repeated_still_tracking_median_ms=float(np.median(timings[2:])),
                         repeated_still_note='performance measurement only, not independent fresh frames'))
    report = dict(sends_input=False,live_verified=False,reference_reviewed=False,rows=rows,
                  limitations=['two static minimap samples only','annotated provisional map',
                               'no measured WASD vectors','no reward-result detector'])
    save_json(output/'report.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
