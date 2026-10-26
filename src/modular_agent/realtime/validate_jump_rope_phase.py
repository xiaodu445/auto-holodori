"""Offline route-C replay, timings and sparse held-out geometry checks. No inputs."""
import argparse
import json
from pathlib import Path
import time
import cv2
import numpy as np
from modular_agent.realtime import jump_rope

DEFAULT_RECORDING='runtime/jump-rope/recordings/20261003-135733-386995'


def point_errors(curve, points, size):
    curve=np.asarray(curve)*size;a=curve[:-1];ab=np.diff(curve,axis=0)
    delta=np.asarray(points)[:,None,:]-a
    fraction=np.clip(np.sum(delta*ab,axis=2)/np.maximum(np.sum(ab*ab,axis=1),1e-6),0,1)
    return np.min(np.linalg.norm(delta-fraction[:,:,None]*ab,axis=2),axis=1)


def validate(root, recording=DEFAULT_RECORDING, annotated=True, reverse=False,state=False,gear=False,output_dir=None,gear_settings_path=None):
    root=Path(root).resolve();recording=root/recording;cost=[];original_load=jump_rope.load
    cv2.setNumThreads(1)
    folder='phase-gear' if gear else 'phase-state' if state else 'phase-reverse' if reverse else 'phase'
    destination=root/'runtime/jump-rope'/folder if output_dir is None else root/Path(output_dir)
    destination.mkdir(parents=True,exist_ok=True)
    if gear:
        settings_path=root/gear_settings_path if gear_settings_path else root/'domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear_config.json'
        settings_used=json.loads(settings_path.read_text(encoding='utf-8-sig'))
        (destination/'settings-used.json').write_text(json.dumps(settings_used,indent=2),encoding='utf-8')
        for key in ('stage_profiles_asset','stage_badges_asset'):
            if key in settings_used:
                asset=root/'domains/hololive_dreams/data/jump_rope_phase'/settings_used[key]
                (destination/asset.name).write_bytes(asset.read_bytes())
    def instrument(*args,**kwargs):
        c,module,v=original_load(*args,**kwargs);vision_type=module.PhaseGearVision if gear else module.PhaseStateVision if state else module.PhaseRopeVision;detect=vision_type.detect
        def timed(self,*args,**kwargs):
            start=time.perf_counter();o=detect(self,*args,**kwargs);cost.append((time.perf_counter()-start)*1000);return o
        vision_type.detect=timed
        return c,module,v
    start=time.perf_counter()
    try:
        jump_rope.load=instrument
        result=jump_rope.replay(root,recording/'screen.avi',timestamp_path=recording/'timestamps.json',phase_rope=True,
            annotated_path=destination/'annotated.avi' if annotated else None,phase_reverse=reverse,phase_state=state,phase_gear=gear,output_path=destination/'replay.json',gear_settings_path=gear_settings_path)
    finally:jump_rope.load=original_load
    rows=json.loads(Path(result['output']).read_text(encoding='utf-8'))
    steps=[];negative=0
    for a,b in zip(rows,rows[1:]):
        x,y=a['observation'],b['observation']
        if x['phase_estimate']['locked'] and y['phase_estimate']['locked']:
            negative+=int(y['phase_estimate']['phase_unwrapped']<x['phase_estimate']['phase_unwrapped'])
            if 0<b['time']-a['time']<=.08:steps.append(float(np.quantile(np.linalg.norm(np.array(x['whole_curve'])-np.array(y['whole_curve']),axis=1),.95)))
    result.update(profile='trajectory_gear_v4' if gear else 'fixed_trajectory_state_v3' if state else 'fixed_trajectory_signed_v2' if reverse else 'fixed_trajectory_phase_v1',seconds=time.perf_counter()-start,
        model_frames=sum(row['observation']['model_exists'] for row in rows),
        visual_phase_frames=sum(row['observation']['phase_estimate']['observed'] for row in rows),
        reverse_phase_steps=negative,p95_step=float(np.quantile(steps,.95)) if steps else None,
        over_006=sum(step>.06 for step in steps),mean_inference_ms=float(np.mean(cost)),p95_inference_ms=float(np.quantile(cost,.95)),
        metric_limits='Accepted visual support is not accuracy; persistent model is not observation. CV-only timings exclude capture/preview.')
    checks=[]
    if recording.resolve()==(root/DEFAULT_RECORDING).resolve():
        labels=json.loads((root/'domains/hololive_dreams/data/jump_rope_samples/whole_rope_validation.json').read_text(encoding='utf-8'))
        for label in labels['samples']:
            o=min(rows,key=lambda row:abs(row['time']-label['time']))['observation']
            errors=point_errors(o['whole_curve'],label['points'],labels['image_size'])
            checks.append(dict(time=label['time'],visually_valid=o['rope_valid'],confidence=o['phase_estimate']['confidence'],
                median_visible_error_px=float(np.median(errors)),max_visible_error_px=float(max(errors))))
    state_file=root/'domains/hololive_dreams/data/jump_rope_samples/state_validation.json'
    if (state or gear) and state_file.exists() and recording.resolve()==(root/DEFAULT_RECORDING).resolve():
        state_labels=json.loads(state_file.read_text(encoding='utf-8'))
        result['sparse_state_checks']=[dict(time=label['time'],expected=label['state'],observed=min(rows,key=lambda r:abs(r['time']-label['time']))['observation']['motion_state']) for label in state_labels['samples']]
        result['sparse_state_limits']=state_labels['limits']
    if gear and rows and rows[0]['observation'].get('difficulty_stage') is not None:
        result['profile']='stage_templates_v1'
        result['difficulty_changes']=[dict(time=row['time'],stage=row['observation']['difficulty_stage']) for i,row in enumerate(rows) if i==0 or row['observation']['difficulty_stage']!=rows[i-1]['observation']['difficulty_stage']]
    result['sparse_manual_checks']=checks
    result['stages']=[dict(seconds=[a,b],frames=sum(a<=row['time']<b for row in rows),valid=sum(row['observation']['rope_valid'] for row in rows if a<=row['time']<b)) for a,b in [(0,15),(15,35),(35,60),(60,90)]]
    if reverse or state or gear:
        result['confirmed_direction_changes']=max(row['observation']['phase_estimate']['reversals'] for row in rows)
        result['negative_rate_frames']=sum(row['observation']['phase_estimate']['rate']<-.05 for row in rows)
    if state or gear:
        result['state_frames']={mode:sum(r['observation']['motion_state']==mode for r in rows) for mode in ('rotation_forward','rotation_reverse','low_swing')}
        result['mode_changes']=max(r['observation']['mode_changes'] for r in rows)
        result['reacquisitions']=max(r['observation']['reacquisitions'] for r in rows)
    output=destination/'report.json';output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project-root',default='.');parser.add_argument('--recording',default=DEFAULT_RECORDING)
    parser.add_argument('--no-video',action='store_true');parser.add_argument('--reverse',action='store_true');parser.add_argument('--state',action='store_true');parser.add_argument('--gear',action='store_true');parser.add_argument('--output-dir');parser.add_argument('--gear-settings');args=parser.parse_args()
    print(json.dumps(validate(args.project_root,args.recording,not args.no_video,reverse=args.reverse,state=args.state,gear=args.gear,output_dir=args.output_dir,gear_settings_path=args.gear_settings),ensure_ascii=False))

if __name__=='__main__':main()
