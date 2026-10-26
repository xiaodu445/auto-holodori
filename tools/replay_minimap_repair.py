"""Replay a recorded minimap session through the live repair engine, no input."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.repair_mapping import RepairMapper
from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recording',type=Path)
    p.add_argument('--reference-config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stride',type=int,default=2)
    a = p.parse_args()
    if a.stride<1:p.error('stride must be positive')
    a.output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(1)
    mapper = RepairMapper(a.reference_config)
    start = time.perf_counter()
    rows = [json.loads(s) for s in (a.recording/'frames.jsonl').read_text().splitlines() if s.strip()]
    with (a.output/'replay-frames.jsonl').open('w',encoding='utf-8') as log:
        for index,row in enumerate(rows[::a.stride]):
            tile = read_image(a.recording/'tiles'/f"{row['frame_id']:06d}.png")
            before = len(mapper.nodes)
            result = mapper.add_tile(tile,np.full(tile.shape[:2],255,np.uint8),row['t'],scene_valid=row.get('hud_score',1)>=.9)
            if len(mapper.nodes)>before:
                mapper.nodes[-1]['source'].update(recording=str(a.recording.resolve()),frame_id=row['frame_id'])
            log.write(json.dumps(dict(frame_id=row['frame_id'],**asdict(result),cone=mapper.cone))+'\n')
            if index%100==0:
                print(f'{index}: {result.reason}, accepted={mapper.accepted}, nodes={len(mapper.nodes)}, edges={len(mapper.edges)}, elapsed={time.perf_counter()-start:.1f}s',flush=True)
            if result.reason=='tile_budget':break
    report = mapper.save(a.output)
    report.update(replay_recording=str(a.recording.resolve()),stride=a.stride,elapsed_seconds=time.perf_counter()-start)
    (a.output/'replay-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='trajectory'},indent=2),flush=True)
    # Diagnostic overlay: red pixels are excluded; original tile remains intact.
    frame = read_image(a.recording/'tiles'/f"{rows[0]['frame_id']:06d}.png")
    from modular_agent.domains.hololive_dreams.minimap_cleanup import exclude_view_cone
    mask,info = exclude_view_cone(frame,np.full(frame.shape[:2],255,np.uint8))
    display = frame.copy();display[mask==0] = (display[mask==0].astype(float)*.4+np.array((0,0,255))*.6).astype(np.uint8)
    write_image(a.output/'cone-diagnostic.png',cv2.resize(display,(492,492),interpolation=cv2.INTER_NEAREST))


if __name__=='__main__':main()
