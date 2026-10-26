"""Offline independent full-atlas likelihood fits, no tracker phase/rate labels."""
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.jump_rope import load,phase_rope_components
WINDOWS=[('reverse_s2_early',36.4,38.2,-1,2),('reverse_s2_late',38.2,39.9,-1,2),('reverse_s3_entry',40.2,41.8,-1,3),('reverse_s3_middle',41.8,43.4,-1,3),('reverse_s3_clear',43.4,45.,-1,3),('reverse_s4_control',65.,68.,-1,4),('reverse_s4_fast_start',71.,73.,-1,4),('reverse_s4_fast_end',73.,74.6,-1,4),('forward_s5_start',80.,82.,1,5),('forward_s5_end',84.9,87.9,1,5)]
def extract(root,output,recording_path=None,windows=None,settings_path=None):
    c,m,_=load(root);v,_=phase_rope_components(root,c,m,gear=True,gear_settings_path=Path(settings_path or 'domains/hololive_dreams/models/jump_rope/jump_rope_directional_exit_config.json'))
    recording=root/(recording_path or 'runtime/jump-rope/recordings/20261003-135733-386995');stamps=json.loads((recording/'timestamps.json').read_text());capture=cv2.VideoCapture(str(recording/'screen.avi'));previous=None;low=high=None;records=[]
    try:
        for i,stamp in enumerate(stamps):
            ok,image=capture.read()
            if not ok:raise ValueError('missing source frame')
            now=stamp['t'];inside=any(a-.1<=now<=b for _,a,b,_,_ in (windows or WINDOWS))
            if not inside:previous=None;continue
            h,w=image.shape[:2];l,t,r,b=c['roi'];image=image[round(t*h):round(b*h),round(l*w):round(r*w)];image=cv2.resize(image,(628,round(image.shape[0]*628/image.shape[1])))
            gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            if previous is None:previous=gray;low=gray.astype(float);high=low.copy();continue
            delta=cv2.absdiff(gray,previous);previous=gray
            if np.mean(delta>30)>.45:low=gray.astype(float);high=low.copy()
            else:low=np.minimum(gray,low+2);high=np.maximum(gray,high-2)
            if i%3:continue
            edges=cv2.Canny(gray,25,70);v.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
            moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8));v.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);v.variation=high-low;v.rotation.prepare(gray)
            q,raw,seen,coverage,moving=v._evidence(v.rotation,gray,np.arange(len(v.rotation.grid)))
            records.append(dict(frame=i,time=now,quality=q.tolist(),coverage=coverage.tolist(),moving=moving.tolist()))
    finally:capture.release()
    output.mkdir(parents=True,exist_ok=True);(output/'evidence.json').write_text(json.dumps(dict(boundary=v.boundary,grid=v.rotation.grid.tolist(),records=records)),encoding='utf-8');return v.boundary,records

def objective(params,t,q,boundary,direction):
    p=np.atleast_2d(params);x=t[None,:]*p[:,0,None]+p[:,1,None]
    phase=(boundary+direction*(x+p[:,2,None]*np.sin(2*np.pi*x)/(2*np.pi)+p[:,3,None]*(1-np.cos(2*np.pi*x))/(2*np.pi)))%1
    z=phase*q.shape[1];lo=np.floor(z).astype(int);fraction=z-lo
    value=q[np.arange(len(t))[None,:],lo%q.shape[1]]*(1-fraction)+q[np.arange(len(t))[None,:],(lo+1)%q.shape[1]]*fraction
    return np.mean(value,axis=1)-.005*np.sum(p[:,2:]**2,axis=1)

def temporal_contrast(quality):
    """Remove persistent spatial support before fitting motion timing."""
    q=np.asarray(quality,dtype=float)
    q=np.maximum(0.,q-np.quantile(q,.25,axis=0))
    return q/(np.max(q,axis=1,keepdims=True)+1e-6)

def fit(records,boundary,direction,remove_static=False):
    t=np.array([r['time'] for r in records]);t-=t[0];q=np.array([r['quality'] for r in records]);best=None;leaders=[]
    if remove_static:q=temporal_contrast(q)
    train=np.arange(len(t))%2==0
    shapes=[(a,b) for a in [-.2,0.,.2] for b in [-.6,-.4,-.2,0.,.2,.4] if a*a+b*b<.81]
    for rate in np.arange(.55,2.401,.025):
        params=np.array([(rate,phase,a,b) for phase in np.arange(96)/96 for a,b in shapes]);scores=objective(params,t[train],q[train],boundary,direction);j=np.argmax(scores);leaders.append((float(scores[j]),params[j].copy()))
    leaders.sort(key=lambda x:x[0],reverse=True)
    refinements=[]
    for _,p in leaders[:8]:
        for steps in [[.01,.005,.05,.05],[.0025,.001,.0125,.0125]]:
            for _ in range(8):
                options=np.vstack([p]+[p+np.eye(4)[i]*step*sign for i,step in enumerate(steps) for sign in [-1,1]])
                legal=(options[:,0]>=.5)&(options[:,0]<=2.5)&(np.sum(options[:,2:]**2,axis=1)<.81);options=options[legal];scores=objective(options,t[train],q[train],boundary,direction);j=np.argmax(scores)
                if np.array_equal(p,options[j]):break
                p=options[j]
        refinements.append((float(objective(p,t[train],q[train],boundary,direction)[0]),p))
    refinements.sort(key=lambda x:x[0],reverse=True);score,p=refinements[0];heldout=float(objective(p,t[~train],q[~train],boundary,direction)[0]);rivals=[(s,x) for s,x in refinements if abs(x[0]-p[0])>.08]
    return dict(rate=float(p[0]),origin=float(p[1]%1),a=float(p[2]),b=float(p[3]),train_score=score,heldout_score=heldout,samples=len(records),cycles=float(p[0]*t[-1]),runner_rate=float(rivals[0][1][0]) if rivals else None,runner_margin=float(score-rivals[0][0]) if rivals else None)

def build(root):
    root=Path(root);output=root/'runtime/jump-rope/clock-library';cache=output/'evidence.json'
    if cache.exists():d=json.loads(cache.read_text());boundary=d['boundary'];records=d['records']
    else:boundary,records=extract(root,output)
    fits=[]
    for name,a,b,direction,stage in WINDOWS:
        rows=[r for r in records if a<=r['time']<=b];result=fit(rows,boundary,direction);result.update(name=name,window=[a,b],direction=direction,stage=stage,verified=False);fits.append(result);print(json.dumps(result),flush=True)
    asset=dict(schema=1,verified=False,boundary=boundary,fits=fits,method='Independent full-grid local grayscale likelihood; harmonic monotone clock, rate .5..2.5; interleaved fit/check frames. No tracker predictions used.',limits='One development recording, CV evidence can follow background/aliases; interleaved frames are not independent holdout. Skill roles require human labels and complete-cycle validation.')
    (output/'fits.json').write_text(json.dumps(asset,indent=2),encoding='utf-8');(root/'domains/hololive_dreams/data/jump_rope_phase/clock_library_v1_trial.json').write_text(json.dumps(asset,indent=2),encoding='utf-8');return asset
if __name__=='__main__':build('.')
