"""Offline replay, judgment-only and explicitly calibrated live entry."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import time
import sys
import traceback
import cv2
from modular_agent.computer import ActionComputer
from modular_agent.core import Action, Outcome
from modular_agent.perception.screen import load_image
from modular_agent.realtime.keyboard import GuardedCapture, run_key_loop


def load(root, config_path=None):
    root = Path(root)
    folder = root/'domains/hololive_dreams/models'
    c = json.loads(Path(config_path or folder/'jump_rope_config.json').read_text(encoding='utf-8-sig'))
    for key,value in {'association_max_age':.12,'association_gate':.035,'association_ambiguity':.008,'curve_max_error':.008,'rope_max_center_slope':.70,'rope_max_curvature':5.0,'rope_max_tangent_slope':1.3}.items(): c.setdefault(key,value)
    c.setdefault('acquisition_timeout',20)
    c.setdefault('rope_stable_frames',3)
    for key in ('rope_max_center_slope','rope_max_curvature','rope_max_tangent_slope','association_max_age','association_gate','association_ambiguity','curve_max_error','acquisition_timeout','fps','timeout','analysis_width','pulse_seconds','short_loss_seconds','long_loss_seconds',
                'max_frame_age','max_observation_gap','prediction_horizon','speed_change_ratio',
                'ground_tolerance'):
        value = c[key]
        if type(value) not in (int,float) or not math.isfinite(value) or value <= 0: raise ValueError('invalid '+key)
    if c['fps']>240 or c['pulse_seconds']>=.25 or c['long_loss_seconds']<=c['short_loss_seconds']:
        raise ValueError('unsafe timing')
    for key in ('fit_samples','ground_frames','analysis_width','rope_stable_frames'):
        if type(c[key]) is not int or c[key]<1: raise ValueError('invalid '+key)
    if not 3<=c['fit_samples']<=120 or not 64<=c['analysis_width']<=2048: raise ValueError('invalid history/width')
    if not 0<c['avatar_threshold']<=1: raise ValueError('invalid avatar threshold')
    slow=c.get('slow_arrival',{})
    for key in ('min_speed','max_speed','approach_max_speed','lead_seconds','danger_y','rearm_distance'):
        if key in slow and (type(slow[key]) not in (int,float) or not math.isfinite(slow[key]) or slow[key]<=0):raise ValueError('invalid slow_arrival '+key)
    if slow and (slow.get('lead_seconds',.10)>.12 or slow.get('danger_y',.57)>=1 or slow.get('min_speed',.03)>=slow.get('approach_max_speed',4.5)):raise ValueError('invalid slow_arrival bounds')
    l,t,r,b=c['roi']
    if not 0<=l<r<=1 or not 0<=t<b<=1: raise ValueError('invalid roi')
    for key in ('avatar_template','avatar_search'):
        x1,y1,x2,y2=c[key]
        if not l<=x1<x2<=r or not t<=y1<y2<=b: raise ValueError('invalid '+key)
    y1,y2=c['rope_y']
    if not t<=y1<y2<=b: raise ValueError('invalid rope_y')
    for x1,x2 in c['rope_probes']:
        if not l<=x1<x2<=r: raise ValueError('invalid probe')
    if len(c['rope_probes'])!=2: raise ValueError('two probes required')
    for low,high in c['rope_hsv_ranges']:
        if len(low)!=3 or len(high)!=3 or any(type(a) is not int or type(z) is not int or not 0<=a<=z<=limit for a,z,limit in zip(low,high,(179,255,255))): raise ValueError('invalid HSV')
    if not c['rope_hsv_ranges']: raise ValueError('empty HSV ranges')
    if c['initial_mode'] not in ('rotation','swing'): raise ValueError('invalid mode')
    calibration=c['calibration']
    if type(calibration['verified']) is not bool: raise ValueError('invalid calibration')
    if calibration['verified']:
        for key in ('input_latency_seconds','safe_airborne_seconds','danger_y','max_prediction_error'):
            value=calibration[key]
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<1: raise ValueError('invalid calibration '+key)
        if calibration['rotation_direction'] not in (-1,1) or type(calibration['rotation_direction']) is not int: raise ValueError('invalid rotation direction')
        if not calibration.get('source'): raise ValueError('calibration evidence required')
    spec=importlib.util.spec_from_file_location('hololive_jump_rope',folder/'jump_rope.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    reference=load_image(root/'domains/hololive_dreams/data/jump_rope_samples/reference.png')[21:]
    return c,module,module.JumpRopeVision(c,reference)


def local_motion_components(root,c,module):
    c.update(local_motion=True,roi=[.475,.03,.655,.68],joint_shape_motion=False)
    reference=load_image(Path(root)/'domains/hololive_dreams/data/jump_rope_samples/reference.png')[21:]
    return module.TrajectoryMotionVision(c,reference),module.TrajectoryMotionController


def whole_rope_components(root,c,module):
    c.update(whole_rope=True,roi=[.17,.02,.88,.72],whole_hand_pose=str(Path(root)/'domains/hololive_dreams/data/jump_rope_samples/whole_hand_pose.png'))
    reference=load_image(Path(root)/'domains/hololive_dreams/data/jump_rope_samples/reference.png')[21:]
    return module.WholeRopeVision(c,reference),module.WholeRopeJudgment


def phase_rope_components(root,c,module, reverse=False,state=False,gear=False,gear_settings_path=None):
    root=Path(root)
    settings_file='jump_rope_phase_gear_config.json' if gear else 'jump_rope_phase_state_config.json' if state else 'jump_rope_phase_reverse_config.json' if reverse else 'jump_rope_phase_config.json'
    if gear_settings_path is not None and not gear:raise ValueError('gear settings require gear profile')
    settings_path=root/gear_settings_path if gear_settings_path else root/'domains/hololive_dreams/models'/settings_file
    settings=json.loads(settings_path.read_text(encoding='utf-8-sig'))
    if type(settings.get('allow_reverse',False)) is not bool:raise ValueError('invalid phase allow_reverse')
    if (reverse or state) and settings.get('allow_reverse') is not True:raise ValueError('reverse profile requires signed tracking')
    if state and (settings.get('state_model') is not True or type(settings.get('zero_timeout')) not in (float,int) or not math.isfinite(settings['zero_timeout']) or not .1<settings['zero_timeout']<2):raise ValueError('invalid phase state model')
    if gear and settings.get('gear_model') is not True:raise ValueError('invalid phase gear model')
    if settings.get('schema')!=1 or settings.get('input_enabled') is not False:raise ValueError('phase route must be judgment-only')
    for name in ('max_rate','max_acceleration'):
        if type(settings.get(name)) not in (float,int) or not math.isfinite(settings[name]) or settings[name]<=0:raise ValueError('invalid phase '+name)
    if type(settings.get('inference_width')) is not int or not 128<=settings['inference_width']<=960:raise ValueError('invalid phase inference_width')
    c.update(whole_rope=True,phase_rope=True,phase_reverse=reverse or state or gear,phase_state=state or gear,phase_gear=gear,roi=[.17,.02,.88,.72],phase_parameters=settings)
    if gear and settings.get('stage_model',False):
        capture_roi=settings['capture_roi'];l,t,r,b=capture_roi
        if not 0<=l<r<=1 or not 0<=t<b<=1:raise ValueError('invalid stage capture ROI')
        c['roi']=capture_roi
        analysis_width=settings.get('capture_analysis_width',c['analysis_width'])
        if type(analysis_width) is not int or not 64<=analysis_width<=2048:raise ValueError('invalid stage capture analysis width')
        c['analysis_width']=analysis_width
    atlas=json.loads((root/settings['atlas']).read_text(encoding='utf-8'))
    if state or gear:
        swing=json.loads((root/settings['swing_atlas']).read_text(encoding='utf-8'))
        vision=(module.PhaseGearVision if gear else module.PhaseStateVision)(c,atlas,swing,module.PhaseRopeVision)
        if settings.get('timed_cycle_playback',False):
            if not gear:raise ValueError('timed playback requires stage-aware gear frontend')
            from modular_agent.realtime.timed_cycle_vision import TimedCycleVision
            vision=TimedCycleVision(root,vision,c,module)
        return vision,module.PhaseRopeJudgment
    return module.PhaseRopeVision(c,atlas),module.PhaseRopeJudgment


def run_jump_rope(root, computer, handle, *, live=False, experimental=False, preview=False, shape_vision=False, local_motion=False, whole_rope=False, config_path=None,
                  should_yield=lambda:False, progress=print, whole_shape=None, phase_rope=False, phase_reverse=False,phase_state=False,phase_gear=False,gear_settings_path=None,mainline=False,focus_on_ready=False):
    if mainline and (phase_rope or whole_rope or local_motion or shape_vision or gear_settings_path):raise ValueError("mainline uses its own guarded profile")
    if mainline and live and not experimental:raise ValueError("mainline input requires explicit experimental-live")
    if phase_gear and not phase_rope:raise ValueError('phase-gear requires phase-rope')
    if phase_gear and (phase_state or phase_reverse):raise ValueError('choose one phase profile')
    if phase_state and not phase_rope:raise ValueError('phase-state requires phase-rope')
    if phase_reverse and phase_state:raise ValueError('choose v2 reverse or v3 state')
    if phase_reverse and not phase_rope:raise ValueError('phase-reverse requires phase-rope')
    if phase_rope and (whole_rope or local_motion or shape_vision or whole_shape):raise ValueError('choose one vision profile')
    if gear_settings_path is not None and not phase_gear:raise ValueError('gear settings require gear profile')
    if phase_rope and (live or experimental):raise ValueError('phase rope is judgment-only')
    if whole_shape is not None and type(whole_shape) is not bool:raise ValueError('invalid whole_shape')
    if whole_shape and not whole_rope:raise ValueError('whole-shape requires whole-rope')
    c,m,v=load(root,config_path)
    if whole_shape is not None:c['whole_shape_model']=whole_shape
    c['joint_shape_motion']=shape_vision
    controller_type=m.JumpRopeController
    if local_motion:v,controller_type=local_motion_components(root,c,m)
    if whole_rope:
        v,controller_type=whole_rope_components(root,c,m)
    if phase_rope:v,controller_type=phase_rope_components(root,c,m,gear=True,gear_settings_path=gear_settings_path) if phase_gear else phase_rope_components(root,c,m,state=True) if phase_state else phase_rope_components(root,c,m,reverse=phase_reverse)
    if whole_rope and (live or experimental):raise ValueError('whole rope is judgment-only until tracking is verified')
    if experimental:
        c['experimental_input']=True
        c['demonstration_crossing_trial']=True
        c['pulse_seconds']=.035
        c['calibration'].update(input_latency_seconds=.06,safe_airborne_seconds=.20,
            danger_y=.57,rotation_direction=1,max_prediction_error=.012,
            source='Short press trial estimates, unverified; long-press recording cannot calibrate short jumps')
    if live and not experimental and not c['calibration']['verified']: raise ValueError('跳绳时机尚未标定；先使用回放/只判断模式')
    phase_folder='phase-gear' if phase_gear else 'phase-state' if phase_state else 'phase-reverse' if phase_reverse else 'phase'
    diagnostic_path=Path(root)/(f'runtime/jump-rope/{phase_folder}/loss-roi.npz' if phase_rope else 'runtime/jump-rope/loss-roi.npz')
    saved=False
    def save_loss(frames):
        nonlocal saved
        import numpy as np
        diagnostic_path.parent.mkdir(parents=True,exist_ok=True)
        # If a window resize occurred, keep only the final compatible client geometry.
        last_bounds=frames[-1][2]
        frames=[frame for frame in frames if frame[2]==last_bounds]
        np.savez_compressed(diagnostic_path,images=np.stack([frame[0] for frame in frames]),
                            times=np.array([frame[1] for frame in frames]),
                            client_bounds=np.array(last_bounds),roi=np.array(c['roi']))
        saved=True
    audio=None;mainline_timing=None;mainline_controller=None
    if mainline:
        c["mainline_live"]=live
        from modular_agent.realtime.jump_rope_mainline import components
        v,mainline_controller,audio,mainline_timing=components(root,c,m,v)
    display=None
    try:
        if preview:
            from modular_agent.realtime.jump_rope_preview import Preview
            display=Preview(c)
        if mainline:
            progress('主线准备完成，等待Go。请开始游戏；空格由程序发送，F12停止。')
            if focus_on_ready:
                from modular_agent.computer.windows import WindowsBackend
                WindowsBackend().focus(handle)
        result=run_key_loop(GuardedCapture(handle,[(.565,.50),(.513,.45),(.618,.45)]),v,mainline_controller if mainline else controller_type(c),computer,c,
            live=live,should_yield=should_yield,progress=progress,on_tracking_loss=save_loss,
            on_frame=display.publish if display else None)
    finally:
        if display:display.close()
        if audio:audio.close()
    if mainline:
        result["mainline_input_timing"]=mainline_timing
        result["audio"]=dict(device=audio.device["name"],source="speaker_loopback",errors=audio.errors,dropped_windows=audio.dropped)
    if display:
        result['preview']=dict(frames=display.frames,mean_render_ms=display.render_ms/max(display.frames,1),error=display.error)
    result['vision_profile']=('trajectory_gear_v4' if phase_gear else 'fixed_trajectory_state_v3' if phase_state else 'fixed_trajectory_signed_v2' if phase_reverse else 'fixed_trajectory_phase_v1') if phase_rope else ('whole_rope_diagnostic_v3_shape' if c.get('whole_shape_model') else 'whole_rope_diagnostic_v2_continuity') if whole_rope else 'trajectory_motion_v6_low_mode' if local_motion else 'joint_shape' if shape_vision else 'baseline'
    if mainline:
        result['vision_profile']='guarded_audio_acceleration_input_trial'
        result['mainline_settings']=c.get('mainline_settings')
    result['capture_roi']=c['roi']
    result['experimental_input']=experimental
    result['joint_shape_motion']=shape_vision
    result['demonstration_crossing_trial']=c.get('demonstration_crossing_trial',False)
    result['control_parameters']=dict(c['calibration'])
    if local_motion:result['control_parameters']['slow_arrival']=c.get('slow_arrival',{})
    if whole_rope:
        result['control_parameters']['whole_continuity']=c.get('whole_continuity',{})
        result['control_parameters']['whole_shape_model']=c.get('whole_shape_model',False)
    if phase_rope or mainline:result['control_parameters']['phase_parameters']=c['phase_parameters']
    if saved:result['loss_roi_record']=str(diagnostic_path.resolve())
    path=Path(root)/'runtime/jump-rope/last-result.json';path.parent.mkdir(parents=True,exist_ok=True)
    session=path.parent/'sessions'/f'{time.time_ns()}.json'
    session.parent.mkdir(parents=True,exist_ok=True)
    result['session_record']=str(session.resolve())
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    session.write_text(payload,encoding='utf-8')
    path.write_text(payload,encoding='utf-8')
    if phase_rope:
        route_path=path.parent/phase_folder/'last-result.json';route_path.parent.mkdir(parents=True,exist_ok=True);route_path.write_text(payload,encoding='utf-8')
    return result


def replay(root, path, config_path=None, title_bar=0, timestamp_path=None,shape_vision=False,local_motion=False,whole_rope=False,annotated_path=None,whole_shape=None,phase_rope=False,phase_reverse=False,phase_state=False,phase_gear=False,output_path=None,gear_settings_path=None):
    if gear_settings_path is not None and not phase_gear:raise ValueError('gear settings require gear profile')
    if phase_gear and not phase_rope:raise ValueError('phase-gear requires phase-rope')
    if phase_gear and (phase_state or phase_reverse):raise ValueError('choose one phase profile')
    if phase_state and not phase_rope:raise ValueError('phase-state requires phase-rope')
    if phase_reverse and phase_state:raise ValueError('choose v2 reverse or v3 state')
    if phase_reverse and not phase_rope:raise ValueError('phase-reverse requires phase-rope')
    if phase_rope and (whole_rope or local_motion or shape_vision or whole_shape):raise ValueError('choose one vision profile')
    if whole_shape is not None and type(whole_shape) is not bool:raise ValueError('invalid whole_shape')
    if whole_shape and not whole_rope:raise ValueError('whole-shape requires whole-rope')
    c,m,v=load(root,config_path);c['joint_shape_motion']=shape_vision
    if whole_shape is not None:c['whole_shape_model']=whole_shape
    controller_type=m.JumpRopeController
    if local_motion:v,controller_type=local_motion_components(root,c,m)
    if whole_rope:
        v,controller_type=whole_rope_components(root,c,m)
    if phase_rope:v,controller_type=phase_rope_components(root,c,m,gear=True,gear_settings_path=gear_settings_path) if phase_gear else phase_rope_components(root,c,m,state=True) if phase_state else phase_rope_components(root,c,m,reverse=phase_reverse)
    controller=controller_type(c)
    stream=cv2.VideoCapture(str(path));fps=stream.get(cv2.CAP_PROP_FPS)
    if not stream.isOpened() or not math.isfinite(fps) or fps<=0: raise ValueError('invalid video')
    stamps=json.loads(Path(timestamp_path).read_text(encoding='utf-8')) if timestamp_path else None
    rows=[];down=False;index=0;writer=None;video_next=None;previous_rendered=None
    try:
        while True:
            ok,image=stream.read()
            if not ok:break
            image=image[title_bar:]
            if not image.size:raise ValueError('empty image')
            h,w=image.shape[:2];l,t,r,b=c['roi']
            local=image[round(t*h):round(b*h),round(l*w):round(r*w)]
            if stamps is not None and index>=len(stamps):raise ValueError('timestamp count mismatch')
            timestamp=stamps[index]['t'] if stamps else index/fps
            if index and timestamp<=rows[-1]['time']:raise ValueError('nonmonotonic replay timestamps')
            observed=v.detect(local,timestamp=timestamp)
            decision=controller.step(observed,timestamp,down);down=decision['down']
            rows.append(dict(time=timestamp,observation=observed,decision=decision));index+=1
            if annotated_path is not None:
                from modular_agent.realtime.jump_rope_preview import render_frame
                rendered=render_frame(local,observed,decision,c,fps)
                if writer is None:
                    destination=Path(annotated_path);destination.parent.mkdir(parents=True,exist_ok=True)
                    writer=cv2.VideoWriter(str(destination),cv2.VideoWriter_fourcc(*'MJPG'),30,(rendered.shape[1]//2*2,rendered.shape[0]//2*2))
                    if not writer.isOpened():raise RuntimeError('annotated video writer unavailable')
                rendered=rendered[:rendered.shape[0]//2*2,:rendered.shape[1]//2*2]
                if video_next is None:video_next=timestamp
                while previous_rendered is not None and video_next<timestamp:
                    writer.write(previous_rendered);video_next+=1/30
                previous_rendered=rendered
        if stamps is not None and index!=len(stamps):raise ValueError('timestamp count mismatch')
    finally:
        stream.release()
        if writer is not None:
            if previous_rendered is not None:writer.write(previous_rendered)
            writer.release()
    out=Path(root)/(('runtime/jump-rope/phase-gear/replay.json' if phase_gear else 'runtime/jump-rope/phase-state/replay.json' if phase_state else 'runtime/jump-rope/phase-reverse/replay.json' if phase_reverse else 'runtime/jump-rope/phase/replay.json') if phase_rope else 'runtime/jump-rope/whole-shape-replay.json' if whole_rope and c.get('whole_shape_model') else 'runtime/jump-rope/whole-rope-replay.json' if whole_rope else 'runtime/jump-rope/replay.json')
    if output_path is not None:out=Path(output_path)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    return dict(frames=index, valid_frames=sum(row['observation']['rope_valid'] if whole_rope or phase_rope else row['observation']['valid'] for row in rows),
                simulated_jumps=controller.jumps, calibrated=c['calibration']['verified'],output=str(out.resolve()))


def main():
    p=argparse.ArgumentParser(description='Jump rope: default judgment only; no per-frame model')
    p.add_argument('--project-root',default='.');p.add_argument('--config');p.add_argument('--live',action='store_true')
    p.add_argument('--mainline',action='store_true',help='guarded audio mainline; add experimental-live for Space trial')
    p.add_argument('--local-motion',action='store_true',help='local curve tracking with frame-difference candidate filtering')
    p.add_argument('--phase-rope',action='store_true',help='independent fixed-trajectory phase route; judgment only')
    p.add_argument('--phase-reverse',action='store_true',help='opt-in signed phase tracker; requires phase-rope, judgment only')
    p.add_argument('--phase-gear',action='store_true',help='independent template/gear model bank; judgment only')
    p.add_argument('--gear-settings',help='explicit gear route settings, for baseline comparison')
    p.add_argument('--phase-state',action='store_true',help='v3 legal three-state tracker; requires phase-rope, judgment only')
    p.add_argument('--whole-rope',action='store_true',help='whole curve and hand anchors; judgment only')
    p.add_argument('--whole-shape',action='store_true',help='experimental constrained rope shape; requires whole-rope')
    p.add_argument('--annotated-video',help='offline replay annotated AVI output')
    p.add_argument('--shape-vision',action='store_true',help='experimental joint curve and motion candidate filtering')
    p.add_argument('--preview',action='store_true',help='show detected rope and parameters without taking focus')
    p.add_argument('--test-space',action='store_true',help='send one 35ms Space pulse to verify game input')
    p.add_argument('--experimental-live',action='store_true',help='send Space using explicitly unmeasured trial timing')
    p.add_argument('--window-handle',type=int);p.add_argument('--replay');p.add_argument('--timestamps')
    p.add_argument('--title-bar',type=int,default=0);p.add_argument('--start-delay',type=float,default=3)
    p.add_argument('--no-focus',action='store_true',help='require manual game focus instead of activating at startup')
    p.add_argument('--verbose',action='store_true',help='print complete timing records')
    a=p.parse_args();root=Path(a.project_root).resolve()
    if a.mainline and (a.local_motion or a.shape_vision or a.whole_rope or a.phase_rope or a.phase_state or a.phase_reverse or a.phase_gear or a.gear_settings or a.test_space or a.replay):p.error('mainline uses its own guarded profile; no replay or mixed route')
    if a.gear_settings and not a.phase_gear:p.error('gear-settings requires phase-gear')
    if a.phase_gear and not a.phase_rope:p.error('phase-gear requires phase-rope')
    if a.phase_gear and (a.phase_state or a.phase_reverse):p.error('choose one phase profile')
    if a.phase_state and not a.phase_rope:p.error('phase-state requires phase-rope')
    if a.phase_state and a.phase_reverse:p.error('choose v2 reverse or v3 state')
    if a.phase_reverse and not a.phase_rope:p.error('phase-reverse requires phase-rope')
    if a.whole_shape and not a.whole_rope:p.error('whole-shape requires whole-rope')
    if sum((a.local_motion,a.shape_vision,a.whole_rope,a.phase_rope))>1:p.error('choose one vision profile')
    if (a.whole_rope or a.phase_rope) and (a.live or a.experimental_live or a.test_space):p.error('whole-rope/phase-rope currently supports judgment only')
    if a.annotated_video and not a.replay:p.error('annotated-video requires replay')
    if a.experimental_live or a.test_space:a.live=True
    cv2.setNumThreads(1)
    if not math.isfinite(a.start_delay) or not 0<=a.start_delay<=30 or a.title_bar<0:p.error('invalid delay/crop')
    if a.replay:
        if a.live:p.error('replay cannot send input')
        print(json.dumps(replay(root,a.replay,a.config,a.title_bar,a.timestamps,shape_vision=a.shape_vision,local_motion=a.local_motion,whole_rope=a.whole_rope,annotated_path=a.annotated_video,whole_shape=True if a.whole_shape else None,phase_rope=a.phase_rope,phase_reverse=a.phase_reverse,phase_state=a.phase_state,phase_gear=a.phase_gear,gear_settings_path=a.gear_settings),ensure_ascii=False));return
    c,_,_=load(root,a.config)
    if a.live and not a.experimental_live and not a.test_space and not c['calibration']['verified']:p.error('尚未标定跳跃时机，不能启用真实输入')
    if a.window_handle is None:
        from modular_agent.computer.windows import WindowsBackend
        windows=[w for w in WindowsBackend().windows() if w['title'].lower()=='hololive-dreams']
        if len(windows)!=1:p.error('specify --window-handle')
        a.window_handle=windows[0]['handle']
    print(f'模式：{"真实输入" if a.live else "只判断，不发送空格"}。{a.start_delay:g}秒后开始。',flush=True)
    if a.experimental_live:print('实验输入：时机参数未实测，可能漏跳或误跳。空格短按35毫秒。',flush=True)
    if a.mainline:print('当前音频主线：请在开始界面启动程序，切回游戏后开始；等待Go消失才允许空格。需开启游戏声音。',flush=True)
    print('启动时切回游戏；运行中切走会停止。F12 或 Ctrl+C 停止。',flush=True)
    with ActionComputer(live=a.live,audit_path=root/'runtime/computer-actions.jsonl') as computer:
        until=time.perf_counter()+a.start_delay
        while time.perf_counter()<until and not computer.stopped:time.sleep(.01)
        if computer.stopped: print('已取消。',flush=True); return 0
        if not a.no_focus and not a.mainline:
            from modular_agent.computer.windows import WindowsBackend
            WindowsBackend().focus(a.window_handle)
        if a.test_space:
            capture=GuardedCapture(a.window_handle,[(.565,.50)])
            try:
                capture.bounds()
                started=time.perf_counter()
                response=computer.perform(Action('key_down',arguments={'key':'space'}))
                if response.outcome != Outcome.SUCCESS:raise RuntimeError(response.message)
                until=started+.035
                while time.perf_counter()<until and not computer.stopped:
                    capture.bounds()
                    time.sleep(.005)
            finally:
                computer.release_all()
                capture.close()
            print('单次空格测试已发送并释放；请观察中间角色是否起跳。未运行绳子控制器。',flush=True)
            return 0
        result=run_jump_rope(root,computer,a.window_handle,live=a.live,experimental=a.experimental_live,preview=a.preview,shape_vision=a.shape_vision,local_motion=a.local_motion,whole_rope=a.whole_rope,whole_shape=True if a.whole_shape else None,phase_rope=a.phase_rope,phase_reverse=a.phase_reverse,phase_state=a.phase_state,phase_gear=a.phase_gear,config_path=a.config,gear_settings_path=a.gear_settings,mainline=a.mainline,focus_on_ready=a.mainline and not a.no_focus)
        print(format_result(result),flush=True)
        print('详细记录：'+str(root/'runtime/jump-rope/last-result.json'),flush=True)
        if a.verbose: print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result['reason'].startswith('exception:') else 0

def format_result(result):
    reason=result['reason']
    messages={
        'window_unavailable_or_unfocused':'游戏失焦、最小化或窗口关闭，已停止；启动后请保持游戏前台。',
        'tracking_region_occluded':'角色或绳子区域被其他窗口遮挡，已停止；请移开遮挡窗口。',
        'initial_recognition_unavailable':'等待20秒仍未建立角色和绳子跟踪，已停止；可能尚未进入游玩或识别配置不适用。',
        'recognition_lost':'角色或绳子的联合跟踪持续丢失，已停止；当前识别仍需校准。',
        'timeout':'达到本次时限，已停止。',
        'cancelled':'人工停止。',
        'damage_zero_miss_goal_failed':'检测到掉血，本轮未达到零失误目标，已停止。',
    }
    detail=next((message for key,message in messages.items() if key in reason),reason)
    if reason=='recognition_lost' and result.get('missing_features'):
        names={'avatar':'中间角色','rope':'绳线'}
        detail+=' 最后一帧未识别：'+ '、'.join(names.get(key,key) for key in result['missing_features'])+'。'
    return f"结束：{detail}\n采集 {result['frames']} 帧，实际 {result['actual_fps']:.1f} FPS；结果 {result['outcome']}。"


def cli():
    try:
        return main() or 0
    except KeyboardInterrupt:
        print('人工停止。',flush=True); return 130
    except Exception as error:
        root=Path(__file__).resolve().parents[3]
        if '--project-root' in sys.argv:
            index=sys.argv.index('--project-root')
            if index+1<len(sys.argv): root=Path(sys.argv[index+1]).resolve()
        path=root/'runtime/jump-rope/startup-error.log'
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(traceback.format_exc(),encoding='utf-8')
        except OSError: pass
        print(f'启动失败：{error}\n错误日志：{path}',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':sys.exit(cli())
