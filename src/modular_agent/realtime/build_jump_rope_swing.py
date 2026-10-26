"""Offline low-swing curve extraction. Never imported by a realtime loop."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def fit_quadratic(x,y,rng):
    if len(x)<80:raise ValueError('insufficient swing pixels')
    ids=rng.choice(len(x),min(len(x),1000),replace=False);x=x[ids];y=y[ids]
    z=(x-.52)/.30;design=np.column_stack([np.ones(len(x)),z,z*z])
    xx=np.linspace(.225,.819,41);zz=(xx-.52)/.30;grid=np.column_stack([np.ones(41),zz,zz*zz])
    best=None;best_count=0
    for _ in range(200):
        ids=rng.choice(len(x),3,replace=False)
        if np.ptp(x[ids])<.30 or np.min(np.diff(np.sort(x[ids])))<.025:continue
        coefficients=np.linalg.lstsq(design[ids],y[ids],rcond=None)[0];curve=grid@coefficients
        if not (.49<curve[0]<.69 and .32<curve[-1]<.53 and -.11<curve[20]-(curve[0]+curve[-1])/2<.19):continue
        keep=abs(design@coefficients-y)<.008;count=int(np.sum(keep))
        if count>best_count and np.ptp(x[keep])>.44:best=coefficients;best_count=count
    if best is None or best_count/len(x)<.35:raise ValueError('unreliable swing fit')
    keep=abs(design@best-y)<.008
    best=np.linalg.lstsq(design[keep],y[keep],rcond=None)[0]
    curve=np.column_stack([xx,grid@best])
    if np.any(curve<0) or np.any(curve>1):raise ValueError('swing outside client')
    return curve,best_count/len(x)


def build(root,recipe_path):
    root=Path(root);recipe=json.loads(Path(recipe_path).read_text(encoding='utf-8'))
    recording=root/recipe['recording'];stamp_path=recording/'timestamps.json';stamps=json.loads(stamp_path.read_text(encoding='utf-8'))
    times=np.array([s['t'] for s in stamps]);stream=cv2.VideoCapture(str(recording/'screen.avi'))
    if not stream.isOpened() or np.any(np.diff(times)<=0):raise ValueError('invalid recording')
    records=[];tiles=[]
    targets=list(np.arange(*recipe['sample_interval'],recipe['sample_seconds']))+list(np.arange(*recipe['endpoint_interval'],recipe['sample_seconds']))
    try:
        for target in targets:
            index=int(np.argmin(abs(times-target)));stream.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=stream.read()
            if not ok:raise ValueError('missing source frame')
            h,w=image.shape[:2];hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
            mask=cv2.inRange(hsv,np.array([18,100,230]),np.array([42,255,255]))
            yy,xx=np.nonzero(mask);x=xx/w;y=yy/h;keep=(x>.23)&(x<.79)&(y>.36)&(y<.69)
            try:curve,support=fit_quadratic(x[keep],y[keep],np.random.default_rng(recipe['seed']))
            except ValueError:continue
            records.append(dict(time=float(times[index]),frame=index,curve=curve.tolist(),training_support=float(support)))
            for a,b in zip(curve,curve[1:]):cv2.line(image,tuple(np.rint(a*[w,h]).astype(int)),tuple(np.rint(b*[w,h]).astype(int)),(0,0,255),2)
            tile=cv2.resize(image,(400,225));cv2.putText(tile,f'{times[index]:.3f}s',(6,20),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,0,255),2);tiles.append(tile)
    finally:stream.release()
    outgoing=[r for r in records if r['time']<recipe['sample_interval'][1]]
    endpoint=[r for r in records if recipe['endpoint_interval'][0]<=r['time']<=recipe['endpoint_interval'][1]]
    if len(outgoing)<4 or not endpoint:raise ValueError('insufficient bounded swing samples')
    final=np.median([r['curve'] for r in endpoint],axis=0)
    # Pointwise medians of different quadratics need not themselves be quadratic.
    final[:,1]=np.polynomial.polynomial.polyval(final[:,0],np.polynomial.polynomial.polyfit(final[:,0],final[:,1],2))
    selected=sorted([r for r in outgoing if r['curve'][20][1]<final[20,1]-.003],key=lambda r:r['curve'][20][1])
    first=selected[0]['curve'][20][1];last=final[20,1];samples=[]
    for record in selected:
        value=(record['curve'][20][1]-first)/(last-first)
        if not samples or value-samples[-1]['coordinate']>.025:samples.append(dict(coordinate=float(value),curve=record['curve'],source_time=record['time']))
    samples.append(dict(coordinate=1.,curve=final.tolist(),source_times=[r['time'] for r in endpoint]))
    data=dict(schema=1,mode='low_swing',name='bounded_quadratic_swing_v1',verified=False,reference_period=recipe['reference_period'],samples=samples,
        provenance=dict(recording=recipe['recording'],timestamps_sha256=hashlib.sha256(stamp_path.read_bytes()).hexdigest(),recipe=recipe,
            method='offline known-yellow ROI, constrained quadratic RANSAC; coordinate ordered by center projection; not dense truth',records=records))
    output=root/recipe['output'];output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    directory=root/'runtime/jump-rope/phase-state';directory.mkdir(parents=True,exist_ok=True)
    if tiles:
        while len(tiles)%3:tiles.append(np.zeros_like(tiles[0]))
        cv2.imwrite(str(directory/'swing-training-contact.jpg'),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)]))
    return dict(samples=len(samples),output=str(output.resolve()))


def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--recipe',default='domains/hololive_dreams/data/jump_rope_phase/swing_recipe.json');a=p.parse_args()
    print(json.dumps(build(a.project_root,a.recipe),ensure_ascii=False))

if __name__=='__main__':main()
