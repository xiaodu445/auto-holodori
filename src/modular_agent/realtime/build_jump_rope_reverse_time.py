"""Independent grayscale curve matching plus signed temporal fitting, offline only."""
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.jump_rope import load,phase_rope_components


def fit(rows,boundary,rate_range=(.60,1.31)):
    good=[r for r in rows if r['quality']>=.45];t=np.array([r['time'] for r in good]);y=np.unwrap(np.array([r['phase'] for r in good])*2*np.pi)/(2*np.pi);t-=t[0]
    best=None
    for rate in np.arange(*rate_range,.005):
        for origin in np.arange(0,1,.01):
            x=t*rate+origin;base=boundary-x;base+=round(float(np.mean(y-base)))
            A=np.stack([-np.sin(2*np.pi*x)/(2*np.pi),-(1-np.cos(2*np.pi*x))/(2*np.pi)],axis=1)
            ab=np.linalg.lstsq(A,y-base,rcond=None)[0]
            if np.linalg.norm(ab)>.9:continue
            error=float(np.mean((base+A@ab-y)**2))
            if best is None or error<best['mse']:best=dict(rate=float(rate),origin=float(origin),a=float(ab[0]),b=float(ab[1]),mse=error,samples=len(good))
    if best is None:raise ValueError('no positive-rate fit')
    return best


def build(root,*,windows=None,output_name="reverse-time",asset_name="reverse_time_v1.json",rate_range=(.60,1.31)):
    root=Path(root);recording=root/'runtime/jump-rope/recordings/20261003-135733-386995';stamps=json.loads((recording/'timestamps.json').read_text())
    c,m,_=load(root);v,_=phase_rope_components(root,c,m,gear=True);vision=v.rotation;windows=windows or [(24.5,28),(28,31.5),(65,68),(68,71)];groups=[[] for _ in windows];capture=cv2.VideoCapture(str(recording/'screen.avi'));previous=None;low=high=None
    try:
        for i,stamp in enumerate(stamps):
            ok,im=capture.read()
            if not ok:raise ValueError('missing frame')
            now=stamp['t'];which=next((j for j,(a,b) in enumerate(windows) if a-.1<=now<=b),None)
            if which is None:previous=None;continue
            h,w=im.shape[:2];l,t,r,b=c['roi'];im=im[round(t*h):round(b*h),round(l*w):round(r*w)];im=cv2.resize(im,(512,round(im.shape[0]*512/im.shape[1])));gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
            if previous is None:low=gray.astype(float);high=low.copy();previous=gray;continue
            delta=cv2.absdiff(gray,previous);low=np.minimum(gray,low+2);high=np.maximum(gray,high-2);previous=gray;vision.prepare(gray)
            q,raw,seen,coverage,moving=vision.evidence(gray,delta,high-low)
            groups[which].append(dict(time=now,scores=q.tolist(),moving=moving.tolist()))
    finally:capture.release()
    output=root/'runtime/jump-rope'/output_name;output.mkdir(parents=True,exist_ok=True);allrows=[];fits=[];N=len(vision.grid)
    for j,records in enumerate(groups):
        score=np.array([r['scores'] for r in records]);cost=-score[0];parents=[]
        travel=(vision.grid[:,None]-vision.grid[None,:])%1 # previous minus next
        for i in range(1,len(records)):
            dt=records[i]['time']-records[i-1]['time'];transition=np.where(travel<=4*dt+.02,.025*((travel-.8*dt)/max(.02,dt))**2,1e6)
            total=cost[:,None]+transition;parent=np.argmin(total,axis=0);parents.append(parent);cost=total[parent,np.arange(N)]-score[i]
        path=[int(np.argmin(cost))]
        for p in reversed(parents):path.append(int(p[path[-1]]))
        path.reverse();rows=[dict(time=r['time'],phase=float(vision.grid[k]),quality=float(score[i,k]),moving=r['moving'][k],window=j) for i,(r,k) in enumerate(zip(records,path))]
        allrows.extend(rows);fits.append(fit(rows,v.boundary,rate_range))
    # First interval is development; repeat interval and later stage are checks.
    trained=fits[0];nodes=np.linspace(0,1,41);angle=nodes+trained['a']*np.sin(2*np.pi*nodes)/(2*np.pi)+trained['b']*(1-np.cos(2*np.pi*nodes))/(2*np.pi);angle[0]=0;angle[-1]=1
    asset=dict(schema=1,verified=False,mode='rotation_reverse_time',profile=dict(clock_nodes=nodes.tolist(),angle_nodes=angle.tolist()),fits=fits,windows=windows,boundary=v.boundary,
        provenance=dict(method='Grayscale full-atlas evidence, negative-direction dynamic programming, independent harmonic time fit; no tracker phase/rate outputs used',limits='Development recording; common spatial atlas assumed. Fits of check windows are diagnostics, not independent manual truth.'))
    (output/'samples.json').write_text(json.dumps(allrows),encoding='utf-8');(output/'fit.json').write_text(json.dumps(asset,indent=2),encoding='utf-8')
    (root/'domains/hololive_dreams/data/jump_rope_phase'/asset_name).write_text(json.dumps(asset,indent=2),encoding='utf-8')
    print(json.dumps(fits),flush=True)
    return asset

if __name__=='__main__':build('.')
