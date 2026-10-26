"""Offline stage evidence extraction. HUD only used to audit this recording."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.stage_badge import StageBadge

RECORDING='runtime/jump-rope/recordings/20261003-135733-386995'

def build(root):
    root=Path(root);recording=root/RECORDING;stamps=recording/'timestamps.json';times=np.array([r['t'] for r in json.loads(stamps.read_text(encoding='utf-8'))]);stream=cv2.VideoCapture(str(recording/'screen.avi'))
    roi=[.025,.22,.13,.30];placeholder=dict(roi=roi,histograms=np.eye(18)[:5].tolist());detector=StageBadge(placeholder,[0,0,1,1]);refs=[]
    windows=[[4.5,8],[24.5,28],[46,48],[71,74],[82,86]]
    for a,b in windows:
        samples=[]
        for t in np.arange(a,b,.1):
            i=int(np.argmin(abs(times-t)));stream.set(cv2.CAP_PROP_POS_FRAMES,i);ok,image=stream.read()
            if not ok:raise ValueError('missing frame')
            vector=detector.vector(image)
            if vector is not None:samples.append(vector)
        if len(samples)<5:raise ValueError('stage badge samples missing')
        median=np.median(samples,axis=0);refs.append((median/max(np.linalg.norm(median),1e-8)).tolist())
    data=dict(schema=1,roi=roi,histograms=refs,provenance=dict(recording=RECORDING,timestamps_sha256=hashlib.sha256(stamps.read_bytes()).hexdigest(),windows=windows,method='Median normalized hue histograms in one fixed small stage badge ROI; sample colors S>80,V>185. No OCR.',limits='One recording, five observed HUD levels only; transition animation or occlusion may delay confirmation.'))
    target=root/'domains/hololive_dreams/data/jump_rope_phase/stage_badges_v1.json';target.write_text(json.dumps(data,indent=2),encoding='utf-8')
    cue=StageBadge(data,[0,0,1,1]);stream.set(cv2.CAP_PROP_POS_FRAMES,0);changes=[]
    for now in times:
        ok,image=stream.read()
        if not ok:raise ValueError('truncated video')
        stage=cue.update(image,float(now))
        if stage is not None:changes.append(dict(time=float(now),stage=stage+1,confidence=cue.confidence))
    stream.release();output=root/'runtime/jump-rope/stage-analysis/badge-validation.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(dict(changes=changes,limits='Offline badge recognition; not rope correctness.'),indent=2),encoding='utf-8');return changes

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');a=p.parse_args();print(json.dumps(build(a.project_root)))
