"""Replay saved real minimaps and original scene gates into a NEW output folder."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import MinimapMapper
from modular_agent.domains.hololive_dreams.patrol_vision import read_image


def main():
    p = argparse.ArgumentParser()
    p.add_argument('session',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--limit',type=int,default=10000)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(1);mapper = MinimapMapper();start = time.perf_counter()
    rows = [json.loads(line) for line in (a.session/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    with (a.output/'frames.jsonl').open('w',encoding='utf-8') as log:
        for i,row in enumerate(rows[:a.limit]):
            image = read_image(a.session/'tiles'/f'{row["frame_id"]:06d}.png')
            n = image.shape[0];mask = np.full((n,n),255,np.uint8)
            result = mapper.add_tile(image,mask,row['t'],scene_valid=row.get('hud_score',1)>=.9)
            log.write(json.dumps(asdict(result))+'\n')
            if i%100==0:
                print(f'{i+1}/{min(len(rows),a.limit)} accepted={mapper.accepted} rejected={mapper.rejected} elapsed={time.perf_counter()-start:.1f}s',flush=True)
    mapper.save(a.output)
    print(f'Done: accepted={mapper.accepted}, rejected={mapper.rejected}; {a.output.resolve()}',flush=True)


if __name__=='__main__':
    main()
