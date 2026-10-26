"""Offline curve search on the fixed AUTO sample; no game input.

Even track IDs train the profile; odd IDs are held out. Tracks come from
automatic association, not hand-labelled truth. Crossing y=.70 is a proxy,
not an observed Perfect deadline. This is not a cross-song validation.
"""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'runtime/rhythm/reviews/20261018-222705-251581/analysis.json').read_text(encoding='utf-8'))
tracks=defaultdict(list)
for f in d['frames']:
    for t in f['tracks']:
        if t['age_ms']<1 and t['color']=='blue':tracks[t['id']].append((f['time'],t['y']))
samples=[]
for ident,points in tracks.items():
    a=np.array(points)
    crossings=[(p,q) for p,q in zip(a[:-1],a[1:]) if p[1]<.70<=q[1] and q[0]-p[0]<.05]
    if not crossings:continue
    p,q=crossings[0];actual=p[0]+(.70-p[1])*(q[0]-p[0])/(q[1]-p[1]);windows=[]
    for cutoff in (.40,.50,.60):
        b=a[(a[:,1]>=.26)&(a[:,1]<=cutoff)&(a[:,0]<actual)][-8:]
        if len(b)<4 or cutoff-b[-1,1]>.05:break
        tm=b[:,0]-b[-1,0];v,intercept=np.polyfit(tm,b[:,1],1)
        if v<=.025 or np.max(abs(b[:,1]-(v*tm+intercept)))>=.012:break
        windows.append((tm,b[:,1]))
    if len(windows)==3:samples.append((ident,actual-b[-1,0],windows, [a[a[:,1]<=cutoff][-1,0] for cutoff in (.40,.50,.60)],actual))

def errors(c,p,subset):
    out=[]
    def phase(y):return np.log(y+c) if abs(p)<1e-8 else ((y+c)**p-1)/p
    for ident,_,windows,lasts,actual in samples:
        if not subset(ident):continue
        row=[]
        for (tm,ys),last in zip(windows,lasts):
            v,b=np.polyfit(tm,phase(ys),1)
            row.append((last+(phase(.70)-phase(ys[-1]))/v-actual)*1000)
        out.append(row)
    return np.array(out)

rank=[]
for c in np.arange(0,2.01,.05):
    for p in np.arange(-2,1.01,.1):
        e=errors(float(c),float(p),lambda i:i%2==0)
        rank.append((float(np.mean(abs(e))),float(c),float(p)))
best=min(rank);print('best training MAE, offset, power',best,'tracks',len(samples))
for c,p in [(0,1),(best[1],best[2]),(0,0),(0,-1)]:
    e=errors(c,p,lambda i:i%2==1)
    print('heldout',c,p,'N',len(e),'signed median',np.median(e,axis=0),'abs p95',np.percentile(abs(e),95,axis=0))

# Exercise the actual controller (association, filtering, locking included).
import importlib.util,sys
spec=importlib.util.spec_from_file_location('curve_evaluation_model',ROOT/'domains/hololive_dreams/models/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
for profile in ({'power':1.,'offset':0.},{'power':-.2,'offset':.15}):
    result=[];missed=[0,0,0]
    for ident,_,windows,lasts,actual in samples:
        if ident%2==0:continue
        row=[]
        for j,cutoff in enumerate((.40,.50,.60)):
            config=m.load_config(ROOT);config['hit_line_y']=.70;config['motion_curve']=profile
            controller=m.RhythmController(config)
            for now,y in tracks[ident]:
                if y>cutoff:break
                controller.decide([m.Note(2,'tap',(.45,y),.08,.02,1)],now)
            locked=[t for t in controller.tracks if t.get('locked')]
            if not locked:missed[j]+=1;row.append(float('nan'))
            else:row.append((max(locked,key=lambda t:t['last'])['arrival']-actual)*1000)
        result.append(row)
    print('controller',profile,'heldout N',len(result),'unlocked',missed,'signed median ms',np.nanmedian(result,axis=0),'abs p95',np.nanpercentile(abs(np.array(result)),95,axis=0))
