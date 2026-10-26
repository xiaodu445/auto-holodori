"""Read-only replay latency and availability; not a ground-truth accuracy test."""
import argparse
from dataclasses import asdict
from collections import Counter
import json
from pathlib import Path
import time
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.minimap_tracking import FastMinimapTracker
from modular_agent.domains.hololive_dreams.patrol_vision import read_image


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('recording',type=Path)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stride',type=int,default=1)
    args = p.parse_args()
    if args.stride<1:p.error('stride must be positive')
    args.output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(1)
    tracker = FastMinimapTracker(args.config)
    rows = [json.loads(s) for s in (args.recording/'frames.jsonl').read_text().splitlines() if s.strip()][::args.stride]
    counts = Counter();latencies = [];unknown_valid = 0
    with (args.output/'observations.jsonl').open('w',encoding='utf-8') as log:
        for row in rows:
            tile = read_image(args.recording/'tiles'/f"{row['frame_id']:06d}.png")
            position = tracker.match_patch(tile,np.full(tile.shape[:2],255,np.uint8),row['t'],scene_valid=row.get('hud_score',1)>=.9)
            counts[position.reason or 'valid'] += 1
            if tracker.timing:latencies.append(tracker.timing['tracking_ms'])
            unknown_valid += bool(position.valid and not tracker.cone.get('valid',False))
            log.write(json.dumps(dict(frame_id=row['frame_id'],position=asdict(position),timing=tracker.timing))+'\n')
    report = dict(frames=len(rows),counts=dict(counts),tracking_ms_p50_p95_max=np.percentile(latencies,[50,95,100]).tolist(),
        cone_unknown_but_valid=unknown_valid,source_recording=str(args.recording.resolve()),source_config=str(args.config.resolve()),
        sends_input=False,accuracy_ground_truth_available=False,live_verified=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
