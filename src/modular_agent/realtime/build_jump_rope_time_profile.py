"""Rebuild the provisional low-swing temporal profile from independent CV samples."""
import argparse
import json
from pathlib import Path
import numpy as np


def build(root,samples='domains/hololive_dreams/data/jump_rope_samples/calibration/yellow-first.json',output='domains/hololive_dreams/data/jump_rope_phase/swing_time_v1.json'):
    root=Path(root);rows=json.loads((root/samples).read_text(encoding='utf-8'))['rows']
    good=[r for r in rows if r['template_error']<.01 and r['fit_support']>.45]
    levels=np.array([.50,.53,.56,.59,.62]);cross=[];windows=[]
    for a,b in [(18.,18.65),(20.4,21.05)]:
        records=sorted([r for r in good if a<=r['time']<=b],key=lambda r:r['center_y'])
        if len(records)<4:raise ValueError('incomplete repeat crossing evidence')
        windows.append(records)
    # np.interp clamps outside the sample range: never count such values as crossings.
    lower=max(records[0]['center_y'] for records in windows)
    upper=min(records[-1]['center_y'] for records in windows)
    levels=levels[(levels>=lower) & (levels<=upper)]
    if len(levels)<3:raise ValueError('insufficient shared crossing evidence')
    for records in windows:
        cross.append(np.interp(levels,[r['center_y'] for r in records],[r['time'] for r in records]))
    period=float(np.median(cross[1]-cross[0]));origin=17.8
    if not 1.<period<4.:raise ValueError('unexpected low swing period')
    sample=[r for r in good if origin<=r['time']<origin+period]
    t=np.array([r['time'] for r in sample]);q=np.array([r['coordinate'] for r in sample]);x=(t-origin)/period
    angle=np.arccos(1-2*q)/(2*np.pi);angle=np.where(x>.5,1-angle,angle);nodes=np.linspace(0,1,21)
    y=np.array([np.median(angle[abs(x-n)<.045]) if np.any(abs(x-n)<.045) else np.interp(n,x,angle) for n in nodes]);y[0]=0;y[-1]=1
    floor=.12;z=np.clip(y-floor*nodes,0,1-floor);weights=np.ones(len(z));weights[[0,-1]]=10000;blocks=[]
    for i,(v,w) in enumerate(zip(z,weights)):
        blocks.append([i,i,float(v*w),float(w)])
        while len(blocks)>1 and blocks[-2][2]/blocks[-2][3]>blocks[-1][2]/blocks[-1][3]:
            b=blocks.pop();a=blocks.pop();blocks.append([a[0],b[1],a[2]+b[2],a[3]+b[3]])
    for a,b,total,w in blocks:z[a:b+1]=total/w
    y=z+floor*nodes;y[0]=0;y[-1]=1
    profile=dict(clock_nodes=nodes.tolist(),angle_nodes=y.tolist())
    data=dict(schema=1,mode='low_swing_time',verified=False,reference_period=period,nominal_rate=1/period,profile=profile,
        provenance=dict(source=samples,method='Independent known-yellow curve fits; repeat ascending center-height crossing times; monotone cubic angular warp with positive slope floor .12',origin=origin,levels=levels.tolist(),crossing_times=[v.tolist() for v in cross],period_samples=(cross[1]-cross[0]).tolist(),shape_error_limit=.01,fit_support_min=.45,limits='Single skill episode; no independent holdout, dense manual truth or other low-speed gears.'))
    (root/output).write_text(json.dumps(data,indent=2),encoding='utf-8')
    return data


def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--samples',default='domains/hololive_dreams/data/jump_rope_samples/calibration/yellow-first.json');p.add_argument('--output',default='domains/hololive_dreams/data/jump_rope_phase/swing_time_v1.json');a=p.parse_args()
    result=build(a.project_root,a.samples,a.output);print(json.dumps(dict(period=result['reference_period'],verified=False)))


if __name__=='__main__':main()
