"""Offline regularized angular fitting, avoiding interpolation across missing endpoints."""
import json
from pathlib import Path
import numpy as np
from modular_agent.realtime.trajectory_bank import AngularWarp


def build(root):
    root=Path(root);folder=root/'domains/hololive_dreams/data/jump_rope_phase'
    old=json.loads((folder/'swing_time_v1.json').read_text(encoding='utf-8'))
    source=root/'domains/hololive_dreams/data/jump_rope_samples/calibration/yellow-first.json'
    rows=json.loads(source.read_text(encoding='utf-8'))['rows'];period=old['reference_period']
    rows=[r for r in rows if 17.6<=r['time']<=21.95 and r['template_error']<.01 and r['fit_support']>.45]
    t=np.array([r['time'] for r in rows]);q=np.array([r['coordinate'] for r in rows]);nodes=np.linspace(0,1,21)
    # Missing endpoint observations are not clamped to the first available angle.
    # Fit a common periodic smooth shape to two repeats; origin is searched too.
    best=None
    for origin in np.linspace(17.60,17.90,61):
        x=((t-origin)/period)%1;angle=np.arccos(1-2*q)/(2*np.pi);angle=np.where(x>.5,1-angle,angle)
        z=x*20;idx=np.minimum(z.astype(int),19);w=z-idx
        A=np.zeros((len(x),21));A[np.arange(len(x)),idx]=1-w;A[np.arange(len(x)),idx+1]=w
        smooth=np.diff(np.eye(21),n=2,axis=0)
        periodic=np.zeros((1,21));periodic[0,[0,1,19,20]]=[-1,1,1,-1]
        matrix=np.vstack([A,.8*smooth,2*periodic]);target=np.r_[angle,np.zeros(20)]
        y=np.r_[0,np.linalg.lstsq(matrix[:,1:-1],target-matrix[:,-1],rcond=None)[0],1]
        # Keep the measured clock monotonic, with positive angular slope floor.
        if np.min(np.diff(y))<.001:continue
        warp=AngularWarp(dict(clock_nodes=nodes.tolist(),angle_nodes=y.tolist()))
        pred=np.array([(1-np.cos(2*np.pi*warp.evaluate(v)[0]))/2 for v in x])
        error=float(np.mean((pred-q)**2));objective=error+.05*float(np.mean((smooth@y)**2))
        if best is None or objective<best[0]:best=(objective,origin,y,error)
    if best is None:raise ValueError('no monotone smooth fit')
    _,origin,y,error=best
    data=dict(schema=1,mode='low_swing_time',verified=False,reference_period=period,nominal_rate=1/period,
        profile=dict(clock_nodes=nodes.tolist(),angle_nodes=y.tolist()),
        provenance=dict(source=str(source.relative_to(root)),origin=origin,samples=len(rows),coordinate_rmse=error**.5,
            method='Two-repeat regularized angular fit; periodic slope penalty; endpoints constrained, missing nodes not clamped',
            limits='Development recording only, common shape across stages unverified; does not correct state-switch geometry seams.'))
    output=folder/'swing_time_v2.json';output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    for name in ('jump_rope_phase_gear_config','jump_rope_stage_config'):
        c=json.loads((root/f'domains/hololive_dreams/models/{name}.json').read_text(encoding='utf-8'))
        c.update(swing_time_profile=data['profile'],swing_time_profile_asset=str(output.relative_to(root)).replace('\\','/'),review_diagnostics=True,swing_boundary_by_branch=True,exit_speed_branches=True)
        if c.get('stage_model'):c.update(initial_stage_forward_only=True,rotation_rate_assist=True)
        (root/f'domains/hololive_dreams/models/{name}_review.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
    return data

def conservative(root):
    root=Path(root);folder=root/'domains/hololive_dreams/data/jump_rope_phase'
    old=json.loads((folder/'swing_time_v1.json').read_text(encoding='utf-8'))
    data=json.loads(json.dumps(old));y=data['profile']['angle_nodes'];y[1]=(y[0]+y[2])/2
    data['provenance']=dict(source='swing_time_v1.json',method='Replace unsupported first internal angular node by interpolation between constrained start and next node; preserve all other calibrated nodes',limits='The replaced node has no direct measurements. Conservative experiment, not engine truth.')
    (folder/'swing_time_v3.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    for name in ('jump_rope_phase_gear_config','jump_rope_stage_config'):
        path=root/f'domains/hololive_dreams/models/{name}.json'
        c=json.loads(path.read_text(encoding='utf-8'));c.update(swing_time_profile=data['profile'],swing_time_profile_asset='domains/hololive_dreams/data/jump_rope_phase/swing_time_v3.json',review_diagnostics=True)
        (path.parent/(path.stem+'_conservative_review.json')).write_text(json.dumps(c,indent=2),encoding='utf-8')
    return data

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--regularized',action='store_true');a=p.parse_args()
    result=build('.') if a.regularized else conservative('.')
    print(json.dumps(result,ensure_ascii=False))
