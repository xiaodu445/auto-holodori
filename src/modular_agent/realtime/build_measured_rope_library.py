"""Offline measured clock cohorts; refuse to invent semantic skill roles."""
import argparse
import json
import math
from pathlib import Path
import numpy as np

def build(windows_path,atlas_path,output):
    data=json.loads(Path(windows_path).read_text(encoding='utf-8'));atlas=json.loads(Path(atlas_path).read_text(encoding='utf-8'));groups=[];rejected=[]
    for window in data['windows']:
        f=window['best'];valid=f['train_score']>=.60 and f['future_check_score']>=.50 and (f['runner_margin'] or 0)>=.05 and f['cycles']>=1.5
        if not valid:rejected.append(dict(start=window['start'],end=window['end'],reason='low fit/future score, ambiguous rate, or insufficient complete cycles'));continue
        key=(window['count_stage_hint'],f['direction'])
        group=next((g for g in groups if g['key']==key and abs(f['rate']/g['center']-1)<.05),None)
        if group is None:group=dict(key=key,center=f['rate'],windows=[]);groups.append(group)
        group['windows'].append(window)
    templates=[]
    for group in groups:
        # Select a measured representative rather than averaging incompatible
        # within-cycle shapes; repeat rates bound residual variation.
        geometry_end=atlas.get('provenance',{}).get('source_window',[0,0])[-1]
        independent=[w for w in group['windows'] if w.get('future_interval',[0])[0]>geometry_end]
        source=max(independent or group['windows'],key=lambda w:w['best']['future_check_score']);f=source['best'];u=np.linspace(0,1,121)
        w=u+f['a']*np.sin(2*np.pi*u)/(2*np.pi)+f['b']*(1-np.cos(2*np.pi*u))/(2*np.pi)
        v=f['direction']*f['rate']*(1+f['a']*np.cos(2*np.pi*u)+f['b']*np.sin(2*np.pi*u))
        acceleration=f['direction']*f['rate']**2*2*np.pi*(-f['a']*np.sin(2*np.pi*u)+f['b']*np.cos(2*np.pi*u))
        rates=[x['best']['rate'] for x in group['windows']]
        templates.append(dict(id=f"count_hint_{group['key'][0]}/{'forward' if group['key'][1]>0 else 'reverse'}/rate_{f['rate']:.4f}",mode='rotation_forward' if f['direction']>0 else 'rotation_reverse',count_stage_hint=group['key'][0],effective_speed_stage=None,skill_role=None,verified=False,status='passed_development_future_window_check',clock_rate=f['rate'],period_seconds=1/f['rate'],rate_samples=rates,clock_nodes=u.tolist(),angle_nodes=w.tolist(),image_phase_velocity_cycles_per_second=v.tolist(),image_phase_acceleration_cycles_per_second2=acceleration.tolist(),source_window=[source['start'],source['end']],source_time_origin=source.get('source_time_origin',source['start']),future_interval=source.get('future_interval'),source_fit=f,cohort_windows=[[x['start'],x['end']] for x in group['windows']],limits='Count-stage hint is not speed stage. Image trajectory phase is not calibrated 3D angular position. Skill role pending cue review.'))
    result=dict(schema=1,verified=False,source_recording=data['recording'],spatial_atlas=str(atlas_path),coordinate='image_trajectory_phase',templates=templates,rejected_windows=rejected,limits='Local CV likelihood and future development frames, not independent recording or human pixel truth. No automatic control integration. No invented speed-stage/skill labels.')
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--windows',required=True);p.add_argument('--atlas',required=True);p.add_argument('--output',required=True);a=p.parse_args();r=build(a.windows,a.atlas,a.output);print(json.dumps(dict(templates=len(r['templates']),rejected=len(r['rejected_windows']))))
