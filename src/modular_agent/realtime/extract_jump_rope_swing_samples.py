"""Reproducible offline rope fits for empirical swing periods. No input calls."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.build_jump_rope_swing import fit_quadratic
from modular_agent.realtime.motion_states import BoundedTrajectory

def extract(root, names=None):
    root=Path(root);recipe_path=root/'domains/hololive_dreams/data/jump_rope_samples/calibration/sampling.json';recipe=json.loads(recipe_path.read_text(encoding='utf-8'));recording=root/recipe['recording']
    stamp_file=recording/'timestamps.json';stamps=json.loads(stamp_file.read_text(encoding='utf-8'));times=np.array([r['t'] for r in stamps])
    atlas=BoundedTrajectory(json.loads((root/'domains/hololive_dreams/data/jump_rope_phase/swing_v1.json').read_text(encoding='utf-8')));grid=np.linspace(0,1,201);curves=atlas.curves(grid)
    stream=cv2.VideoCapture(str(recording/'screen.avi'))
    if not stream.isOpened():raise ValueError('missing recording')
    results={}
    try:
        for name in names or recipe['segments']:
            settings=recipe['segments'][name];rows=[]
            for start,end in settings['intervals']:
                for target in np.arange(start,end,recipe['sample_seconds']):
                    index=int(np.argmin(abs(times-target)));stream.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=stream.read()
                    if not ok:raise ValueError('missing source frame')
                    h,w=image.shape[:2];hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV);mask=cv2.inRange(hsv,np.array(settings['hsv_low']),np.array(settings['hsv_high']))
                    yy,xx=np.nonzero(mask);x=xx/w;y=yy/h;l,t,r,b=recipe['roi'];keep=(x>l)&(x<r)&(y>t)&(y<b)
                    if settings['exclude_bodies']:
                        for cx,width,top,bottom in [(.37,.022,.43,.66),(.47,.02,.40,.63),(.565,.025,.37,.62),(.65,.022,.35,.59),(.73,.022,.33,.57)]:keep&=~((abs(x-cx)<width)&(y>top)&(y<bottom))
                    try:curve,support=fit_quadratic(x[keep],y[keep],np.random.default_rng(recipe['seed']))
                    except ValueError:continue
                    errors=np.mean(np.linalg.norm(curves-curve,axis=2),axis=1);j=int(np.argmin(errors))
                    rows.append(dict(time=float(times[index]),coordinate=float(grid[j]),template_error=float(errors[j]),fit_support=float(support),center_y=float(curve[20,1])))
            data=dict(verified=False,rows=rows,source=recipe['recording'],recipe=settings,seed=recipe['seed'],timestamps_sha256=hashlib.sha256(stamp_file.read_bytes()).hexdigest(),limits=recipe['limits'])
            output=root/settings['output'];output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2),encoding='utf-8');results[name]=len(rows)
    finally:stream.release()
    return results

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--segment',action='append');a=p.parse_args();print(json.dumps(extract(a.project_root,a.segment)))

if __name__=='__main__':main()
