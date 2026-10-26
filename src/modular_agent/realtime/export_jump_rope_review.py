"""Export exact source-frame diagnostics and a standalone annotation viewer. No input."""
import os
import argparse
import hashlib
import html
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.realtime.jump_rope_preview import render_frame


def export(root, replay, recording, output, settings, reuse_images=False, image_source=None):
    root=Path(root).resolve();output=root/output;output.mkdir(parents=True,exist_ok=True)
    rows=json.loads((root/replay).read_text(encoding='utf-8'));stamps=json.loads((root/recording/'timestamps.json').read_text(encoding='utf-8'))
    if len(stamps)!=len(rows):raise ValueError('source/replay frame count mismatch')
    for stamp,row in zip(stamps,rows):
        if abs(stamp['t']-row['time'])>1e-7:raise ValueError('source/replay timestamps differ')
    config=json.loads((root/'domains/hololive_dreams/models/jump_rope_config.json').read_text(encoding='utf-8'))
    params=json.loads((root/settings).read_text(encoding='utf-8-sig'));config.update(roi=[0,0,1,1],whole_rope=True,phase_rope=True,phase_reverse=True,phase_state=True,phase_gear=True,phase_parameters=params)
    images=output/'frames'
    if image_source is not None:
        source=root/image_source;manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
        source_params=dict(manifest['settings']);new_params=dict(params)
        source_params.pop('acceleration_evidence_policy',None);new_params.pop('acceleration_evidence_policy',None)
        if source_params!=new_params:raise ValueError('shared images require otherwise identical rendering settings')
        original=json.loads((root/manifest['replay']).read_text(encoding='utf-8'))
        ignored={'audio_review','terminal_stage_policy'} # Diagnostic-only; neither is painted in render_frame.
        if len(original)!=len(rows) or any(a['time']!=b['time'] or a['decision']!=b['decision'] or {k:v for k,v in a['observation'].items() if k not in ignored}!={k:v for k,v in b['observation'].items() if k not in ignored} for a,b in zip(original,rows)):
            raise ValueError('shared image geometry/render inputs differ')
        images=source/'frames'
        if any(not (images/f'{i:06d}.jpg').is_file() for i in range(len(rows))):raise ValueError('shared images incomplete')
        reuse_images=True
        del original
    else:images.mkdir(exist_ok=True)
    image_prefix=Path(os.path.relpath(images,output)).as_posix()
    details=[];previous=None;jsonl=output/'frames.jsonl' 
    capture=cv2.VideoCapture(str(root/recording/'screen.avi'))
    try:
        with jsonl.open('w',encoding='utf-8') as stream:
            for i,row in enumerate(rows):
                ok,frame=capture.read()
                if not ok:raise ValueError('source video ended early')
                o=row['observation'];p=o['phase_estimate'];time=row['time']
                # Native frame indices never resampled to a 30 FPS movie timeline.
                delta=0. if previous is None or not o['whole_curve'] or not previous['whole_curve'] else float(np.quantile(np.linalg.norm(np.array(o['whole_curve'])-previous['whole_curve'],axis=1),.95))
                changed=previous is not None and previous.get('selected_hypothesis')!=o.get('selected_hypothesis')
                d=dict(frame=i,time=time,dt=0. if i==0 else time-rows[i-1]['time'],image=f'{image_prefix}/{i:06d}.jpg',
                    stage=o.get('difficulty_stage'),count_stage=o.get('count_stage'),effective_speed_stage=o.get('effective_speed_stage'),stage_source=o.get('stage_source'),stage_confidence=o.get('stage_confidence'),stage_change=o.get('stage_change'),
                    terminal_stage_policy=o.get('terminal_stage_policy'),motion_state=o['motion_state'],tracking=o['tracking_status'],locked=p['locked'],visual=o['rope_valid'],
                    clock=p['phase_unwrapped'],coordinate=p['phase'],rate=p['clock_rate'],velocity=p['rate'],acceleration=p['template_acceleration'],
                    confidence=p['confidence'],quality=o['phase_visual_quality'],support=o['whole_coverage'],hypothesis=o['selected_hypothesis'],
                    pending=o.get('mode_candidate'),pending_seconds=o.get('confirmation_pending_seconds'),confirmation_seconds=o.get('confirmation_required_seconds'),
                    event=o.get('last_motion_event'),candidate_changed=changed,curve_step_p95=delta,episode=o.get('low_swing_episode'),entry_direction=o.get('low_entry_direction'),
                    swing_pass=o.get('swing_pass'),exit_half_allowed=o.get('exit_half_allowed'),exit_boundary=o.get('exit_boundary'),exit_rotation_join=o.get('exit_rotation_join'),template_label=o.get('template_label'),template_calibration=o.get('template_calibration'),stage_role=o.get('branch_role'),landing=o.get('landing_number'),branch=o.get('last_landing_branch'),candidates=o.get('phase_alternatives',[]),
                    decision=row['decision'],observation=o)
                stream.write(json.dumps(d,ensure_ascii=False)+'\n')
                # Viewer contains compact fields; full observation remains in JSONL.
                details.append({k:v for k,v in d.items() if k not in ('observation','decision')})
                if reuse_images and (images/f'{i:06d}.jpg').exists():
                    previous=o
                    continue
                canvas=render_frame(frame,o,row['decision'],config,0)
                canvas=cv2.resize(canvas,(960,round(canvas.shape[0]*960/canvas.shape[1])))
                cv2.putText(canvas,f'FRAME {i:06d} | {time:.6f}s | visual={o["rope_valid"]} | switch={changed}',(8,24),cv2.FONT_HERSHEY_SIMPLEX,.53,(255,255,255),2,cv2.LINE_AA)
                if not cv2.imwrite(str(images/f'{i:06d}.jpg'),canvas,[cv2.IMWRITE_JPEG_QUALITY,82]):raise OSError('frame image write failed')
                previous=o
                if i%500==0:print(f'Exported {i}/{len(rows)}',flush=True)
        if capture.read()[0]:raise ValueError('source video has extra frames')
    finally:capture.release()
    template=Path(__file__).with_name('jump_rope_review.html').read_text(encoding='utf-8')
    (output/'index.html').write_text(template.replace('/*FRAME_DATA*/',json.dumps(details,ensure_ascii=False).replace('</',r'<\/')),encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps(dict(frames=len(rows),recording=str(recording),replay=str(replay),settings=params,
        image_source=str(image_source) if image_source is not None else None,
        replay_sha256=hashlib.sha256((root/replay).read_bytes()).hexdigest(),
        limits='One image per original captured frame; unavailable stage remains null. No generated labels are human truth. Full observations in frames.jsonl; no keyboard input.'),ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(frames=len(rows),viewer=str((output/'index.html').resolve()),jsonl=str(jsonl.resolve()))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--replay',required=True);p.add_argument('--recording',default='runtime/jump-rope/recordings/20261003-135733-386995');p.add_argument('--output',required=True);p.add_argument('--settings',required=True);a=p.parse_args()
    print(json.dumps(export(a.project_root,a.replay,a.recording,a.output,a.settings),ensure_ascii=False))
