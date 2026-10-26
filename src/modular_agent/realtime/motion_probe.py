"""Explicit stationary camera / annotated open-ground W measurements."""
import argparse
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import threading
import time
import cv2
import numpy as np
from modular_agent.core import Action,Outcome
from modular_agent.domains.hololive_dreams.motion_dynamics import camera_headings,fit_camera,fit_forward,measure_cruise
from modular_agent.domains.hololive_dreams.minimap_cleanup import exclude_view_cone
from modular_agent.domains.hololive_dreams.minimap_tracking import FastMinimapTracker
from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image
from modular_agent.realtime.patrol import ROOT,read_json,save_json,latest_repaired_config,route_input_lease


def validated_walk_mask(config_path,mask_path):
    from modular_agent.domains.hololive_dreams.navigation_annotations import digest
    config_path=Path(config_path).resolve();mask_path=Path(mask_path).resolve()
    config=read_json(config_path);route=read_json(mask_path.parent/'planned-route.json')
    if route.get('map_sha256')!=digest(config_path.parent/config['reference']):
        raise ValueError('可走掩膜与当前定位底图指纹不符')
    if Path(route.get('planning_mask','')).name!=mask_path.name:
        raise ValueError('请选择路线导出的 planning-mask.png')
    mask=read_image(mask_path)[:,:,0]
    if mask.shape!=read_image(config_path.parent/config['reference']).shape[:2]:raise ValueError('可走掩膜尺寸不符')
    return mask


def require_open_disk(mask,position,duration,speed_bound=180):
    if not position.valid:raise ValueError('需要可靠的人物位置')
    radius=int(np.ceil(duration*speed_bound+8));x,y=round(position.x),round(position.y)
    h,w=mask.shape
    if not (radius<=x<w-radius and radius<=y<h-radius):raise ValueError(f'需要半径{radius}地图像素的开阔可走区域')
    yy,xx=np.ogrid[-radius:radius+1,-radius:radius+1]
    if not np.all(mask[y-radius:y+radius+1,x-radius:x+radius+1][xx*xx+yy*yy<=radius*radius]):
        raise ValueError(f'W探测周围半径{radius}地图像素内存在未知/禁行区；请换开阔处或减小持键时长')


def require_forward_space(mask,position,duration,*,open_ground=False):
    if not position.valid or not np.isfinite([position.x,position.y]).all():raise ValueError('需要可靠的人物位置')
    if mask is not None:return require_open_disk(mask,position,duration)
    if not open_ground:raise ValueError('请选择人工可走掩膜，或显式选择开阔处直接测试')
    if not .05<=duration<=2:raise ValueError('W测量每次最长2秒')


def observed_hold(computer,duration,check,observe,*,coast=.9,on_press=lambda:None,on_release=lambda stamp:None):
    """Release deadline runs independently of expensive vision. No retry of W."""
    if not .05<=duration<=2 or not .2<=coast<=2:raise ValueError('invalid probe duration')
    if computer.keys or computer.buttons:raise RuntimeError('probe requires exclusive released inputs')
    check();result=computer.perform(Action('key_down',arguments={'key':'w'}))
    if result.outcome!=Outcome.SUCCESS:
        computer.release_all();raise RuntimeError(result.message)
    start=time.perf_counter();released=[];errors=[];cancel=threading.Event()
    def watchdog():
        try:
            while not cancel.is_set() and time.perf_counter()-start<duration:
                check()
                if computer.stopped:raise RuntimeError('cancelled')
                cancel.wait(.005)
        except Exception as error:errors.append(error)
        finally:
            try:computer.release_all()
            except Exception as error:errors.append(error)
            stamp=time.perf_counter();released.append(stamp)
            try:on_release(stamp)
            except Exception as error:errors.append(error)
    worker=threading.Thread(target=watchdog,daemon=True);samples=[]
    try:
        on_press();worker.start()
        while time.perf_counter()-start<duration+coast:
            if errors:raise errors[0]
            check();sample=observe();samples.append(dict(t=sample['stamp']-start,x=sample['x'],y=sample['y']))
            time.sleep(.005)
        if errors:raise errors[0]
    finally:
        cancel.set()
        if worker.ident is not None:worker.join(timeout=1)
        computer.release_all()
    if worker.is_alive():raise RuntimeError('probe watchdog failed to terminate')
    return dict(held_seconds=released[0]-start,samples=samples)


def turn_step(computer,counts,check,sent):
    if type(counts) is not int or not 1<=abs(counts)<=40:raise ValueError('invalid mouse probe')
    if computer.keys or computer.buttons:raise RuntimeError('turn probe requires released inputs')
    previous=0
    for index in range(1,7):
        check();target=round(counts*index/6);delta=target-previous
        result=computer.perform(Action('move_relative',arguments=dict(dx=delta,dy=0)))
        if result.outcome!=Outcome.SUCCESS:raise RuntimeError(result.message)
        sent(delta);previous=target;time.sleep(.01)
    check()


class SmoothTurn:
    """Small relative moves at 100Hz, independent of capture and fitting."""
    def __init__(self,computer,rate,budget,check,sent):
        if not 20<=abs(rate)<=400 or not 1<=budget<=16000:raise ValueError('invalid continuous turn budget')
        if computer.keys or computer.buttons:raise RuntimeError('turn probe requires exclusive released inputs')
        self.computer=computer;self.rate=rate;self.budget=budget;self.check=check;self.sent=sent
        self.cancel=threading.Event();self.error=None;self.count=0
        self.worker=threading.Thread(target=self.run,daemon=True)

    def run(self):
        previous=time.perf_counter();credit=0
        try:
            while not self.cancel.is_set() and abs(self.count)<self.budget:
                self.check();now=time.perf_counter()
                credit=min(8,credit+abs(self.rate)*min(now-previous,.02));previous=now
                step=min(4,int(credit),self.budget-abs(self.count))
                if step:
                    delta=step if self.rate>0 else -step
                    result=self.computer.perform(Action('move_relative',arguments=dict(dx=delta,dy=0)))
                    if result.outcome!=Outcome.SUCCESS:raise RuntimeError(result.message)
                    self.count+=delta;credit-=step;self.sent(delta)
                self.cancel.wait(.01)
        except Exception as error:self.error=error

    def start(self):self.worker.start()
    def stop(self):
        self.cancel.set()
        if self.worker.ident is not None:self.worker.join(timeout=1)
        if self.worker.is_alive():raise RuntimeError('mouse worker failed to stop')


def run(args):
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.computer.controller import ActionComputer
    from modular_agent.realtime.keyboard import GuardedCapture
    from modular_agent.realtime.route_scene import RouteSceneGate
    from modular_agent.realtime.minimap_preview import MapPreview
    tracker=FastMinimapTracker(args.config);backend=WindowsBackend()
    matches=[w for w in backend.windows() if w['title'].casefold()==args.window_title.casefold()]
    if len(matches)!=1:raise ValueError('需要唯一游戏窗口')
    mask=validated_walk_mask(args.config,args.walk_mask) if args.phase=='forward' and args.walk_mask else None
    if args.phase=='forward' and mask is not None and mask.shape!=tracker.reference.shape[:2]:
        raise ValueError('W标定需要与当前底图尺寸一致的人工可走掩膜')
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'tiles').mkdir()
    viewer=MapPreview('Motion probe - F12 stops',np.zeros((330,600,3),np.uint8))
    print(f'{args.start_delay:g}秒内切回游戏；{args.phase}标定，F12/失焦停止。',flush=True)
    time.sleep(args.start_delay)
    capture=None;computer=None;rows=[];trials=[];reason='unknown';report=None;cruise=None;state={'frame':0.,'semantic':0.,'ok':False};frame_id=0
    camera_images=[];counts=[0];headings=[];latest=None;gate=RouteSceneGate(ROOT);dispatched=[];mouse_count=0;turner=None
    try:
        capture=GuardedCapture(matches[0]['handle'],[(.11,.18),(.5,.5),(.87,.82)]);bounds=capture.bounds()
        computer=ActionComputer(live=True,backend=backend,audit_path=args.output/'input-audit.jsonl')
        def check():
            if args.stop_file and args.stop_file.exists():raise RuntimeError('stop_file')
            if computer.stopped:raise RuntimeError('cancelled')
            if args.phase=='camera' and any(backend.api.GetAsyncKeyState(ord(key))&0x8000 for key in 'WASD'):
                raise RuntimeError('camera_probe_requires_stationary_character')
            if capture.bounds()!=bounds:raise RuntimeError('window_moved_or_resized')
            now=time.perf_counter()
            if not state['ok'] or now-state['frame']>.5 or now-state['semantic']>.7:raise RuntimeError('stale_or_blocked_scene')
        def observe(require_position=False):
            nonlocal frame_id,latest
            if args.stop_file and args.stop_file.exists():raise RuntimeError('stop_file')
            image,rect=capture.grab((0,0,1,1));stamp=time.perf_counter();count_snapshot=mouse_count
            if rect!=bounds:raise RuntimeError('window_moved_or_resized')
            if stamp-state['semantic']>.25:
                ok,hud=gate.read(image);state['semantic']=stamp
            else:ok,hud=gate.hud.read(image)
            state['ok']=ok;state['frame']=stamp
            if not ok:raise RuntimeError('free_scene_lost_or_disabled')
            position=tracker.locate(image,stamp,scene_valid=True)
            if require_position and not position.valid:raise RuntimeError('localization_lost')
            patch,valid=tracker.spec.crop(image,mask_icons=False);patch=cv2.resize(patch,(164,164))
            frame_id+=1;write_image(args.output/'tiles'/f'{frame_id:06d}.png',patch)
            row=dict(frame_id=frame_id,stamp=stamp,mouse_count=count_snapshot,position=asdict(position) if position else None)
            rows.append(row);latest=(patch,position,stamp,count_snapshot)
            canvas=cv2.resize(patch,(328,328),interpolation=cv2.INTER_NEAREST)
            _,actor=exclude_view_cone(patch,np.full((164,164),255,np.uint8))
            if actor.get('valid'):
                theta=np.deg2rad(actor['heading_degrees']);end=(164+round(55*np.cos(theta)),164+round(55*np.sin(theta)))
                cv2.arrowedLine(canvas,(164,164),end,(255,255,255),2)
            canvas=cv2.copyMakeBorder(canvas,40,0,0,280,cv2.BORDER_CONSTANT,value=(25,25,25))
            cv2.putText(canvas,'WHITE actor | ORANGE camera | F12 STOP',(5,24),cv2.FONT_HERSHEY_SIMPLEX,.43,(230,230,230),1)
            if position and position.valid:cv2.putText(canvas,f'Position {position.x:.1f}, {position.y:.1f}',(335,70),cv2.FONT_HERSHEY_SIMPLEX,.43,(230,230,230),1)
            if args.phase!='camera' or not camera_images:
                if not viewer.show(canvas):raise RuntimeError('preview_closed')
            return dict(stamp=stamp,x=position.x if position else 0,y=position.y if position else 0)
        observe()
        if any(backend.api.GetAsyncKeyState(ord(key))&0x8000 for key in 'WASD'):
            raise RuntimeError('请先松开WASD再开始标定')
        if args.phase=='camera':
            camera_images.append(latest[0].copy())
            camera_position=latest[1] if latest[1].valid else None
            def mouse_sent(delta):
                nonlocal mouse_count
                dispatched.append(dict(kind='mouse',dx=delta,stamp=time.perf_counter()));mouse_count+=delta
            turner=SmoothTurn(computer,240 if args.mouse_step>0 else -240,
                args.steps*abs(args.mouse_step),check,mouse_sent)
            turner.start();camera_start=time.perf_counter();last_fit=0
            while time.perf_counter()-camera_start<90:
                if turner.error:raise turner.error
                if not turner.worker.is_alive():reason='camera_count_budget_incomplete';break
                check()
                observe();camera_images.append(latest[0].copy());counts.append(latest[3])
                if latest[1].valid:
                    if camera_position is None:camera_position=latest[1]
                    if np.hypot(latest[1].x-camera_position.x,latest[1].y-camera_position.y)>3:
                        raise RuntimeError('camera_probe_character_moved')
                if len(camera_images)>=8 and time.perf_counter()-last_fit>=.6:
                    indexes=np.unique(np.linspace(0,len(camera_images)-1,min(96,len(camera_images))).astype(int))
                    headings,quality=camera_headings([camera_images[i] for i in indexes]);last_fit=time.perf_counter()
                    try:report=fit_camera([counts[i] for i in indexes],headings)
                    except ValueError:report=None
                    canvas=cv2.resize(latest[0],(328,328),interpolation=cv2.INTER_NEAREST)
                    if headings[-1] is not None:
                        for angle,color,length in ((headings[-1],(0,150,255),110),
                            (headings[-1]-quality[-1]['half_angle_degrees'],(0,200,200),130),
                            (headings[-1]+quality[-1]['half_angle_degrees'],(0,200,200),130)):
                            theta=np.deg2rad(angle);cv2.line(canvas,(164,164),(164+round(length*np.cos(theta)),164+round(length*np.sin(theta))),color,2)
                    progress=report['directed_advance_degrees'] if report else 0
                    canvas=cv2.copyMakeBorder(canvas,35,0,0,280,cv2.BORDER_CONSTANT,value=(25,25,25))
                    text=f'CAMERA {progress:.1f}/360 deg | counts {mouse_count}' if report else f'CAMERA uncertain | counts {mouse_count}'
                    cv2.putText(canvas,text,(5,23),cv2.FONT_HERSHEY_SIMPLEX,.45,(230,230,230),1)
                    if not viewer.show(canvas):raise RuntimeError('preview_closed')
                    if report and report['full_turn_observed'] and report['directed_advance_degrees']>=365:reason='full_turn_observed';break
                time.sleep(.02)
            else:reason='camera_time_budget_incomplete'
            turner.stop()
            if len(camera_images)>=8:
                headings,quality=camera_headings(camera_images)
                save_json(args.output/'camera-samples.json',dict(counts=counts,headings=headings,quality=quality))
                report=fit_camera(counts,headings)
                if reason=='full_turn_observed' and not report['full_turn_observed']:reason='camera_full_turn_recheck_failed'
        else:
            # Two-frame localization warmup without any input.
            warmup=time.perf_counter()
            while not latest[1].valid:
                if time.perf_counter()-warmup>3:raise RuntimeError('initial_localization_timeout')
                observe()
            stationary=[];start_stationary=time.perf_counter()
            while time.perf_counter()-start_stationary<.35:
                observe(True);stationary.append((latest[1].x,latest[1].y))
            if len(stationary)<3 or np.max(np.linalg.norm(np.asarray(stationary)-stationary[0],axis=1))>1.5:
                raise RuntimeError('角色尚未静止，拒绝开始W测量')
            for duration in args.holds:
                require_forward_space(mask,latest[1],duration,open_ground=args.open_ground)
                baseline=latest[1];start_pose=(baseline.x,baseline.y);held_trace=[];trial_start=time.perf_counter()
                def forward_observation():
                    sample=observe(True)
                    if np.hypot(sample['x']-start_pose[0],sample['y']-start_pose[1])>duration*180+6:
                        raise RuntimeError('probe_displacement_exceeds_safe_envelope')
                    held_trace.append(sample)
                    if .4<sample['stamp']-trial_start<duration:
                        previous=next((s for s in reversed(held_trace) if sample['stamp']-s['stamp']>=.25),None)
                        if previous and np.hypot(sample['x']-previous['x'],sample['y']-previous['y'])<.6:
                            raise RuntimeError('no_progress_while_w_held')
                    return sample
                result=observed_hold(computer,duration,check,forward_observation,coast=args.coast,
                    on_press=lambda:dispatched.append(dict(kind='w',down_at=time.perf_counter())),
                    on_release=lambda stamp:dispatched[-1].update(released_at=stamp))
                result['samples'].insert(0,dict(t=0.,x=baseline.x,y=baseline.y))
                trials.append(result);save_json(args.output/'forward-samples.json',dict(trials=trials))
                cruise=measure_cruise(trials);save_json(args.output/'speed-measurement.json',cruise)
                if np.linalg.norm(np.asarray([latest[1].x-baseline.x,latest[1].y-baseline.y]))<2:
                    raise RuntimeError('no_forward_displacement_no_retry')
                tail=result['samples'][-3:]
                if np.hypot(tail[-1]['x']-tail[0]['x'],tail[-1]['y']-tail[0]['y'])>1.5:
                    raise RuntimeError('still_moving_after_coast_budget')
            report=fit_forward(trials);reason='forward_measured'
    except (Exception,KeyboardInterrupt) as error:
        reason=str(error) or 'ctrl_c';report=None
    finally:
        try:
            if turner:turner.stop()
            if computer:computer.close()
        finally:
            if capture:capture.close()
            viewer.close()
            save_json(args.output/'observations.json',dict(frames=rows,input_events=dispatched))
            if report:
                report['protocol']=dict(mouse_mode='continuous',requested_counts_per_second=240,mouse_tick_seconds=.01,maximum_tick_counts=4,
                    held_seconds=args.holds,window_bounds=list(bounds),units='normalized minimap pixels / seconds / injected relative mouse counts')
            if args.phase=='camera':save_json(args.output/'camera-raw-counts.json',dict(counts=counts,dispatched_count=mouse_count))
            save_json(args.output/'summary.json',dict(reason=reason,phase=args.phase,report=report,
                source_config=str(args.config.resolve()),sends_input=bool(dispatched),inputs_dispatched=len(dispatched),live_verified=False,
                speed_measurement=cruise,
                ground_check='annotation_mask' if mask is not None else 'user_selected_open_ground' if args.phase=='forward' else 'stationary_camera'))
            if report:
                suffix='calibration' if args.phase!='camera' or report['full_turn_observed'] else 'candidate-incomplete'
                save_json(args.output/f'{args.phase}-{suffix}.json',report)
    print(f'标定结束：{reason}；结果 {args.output.resolve()}',flush=True)
    return 0 if report and (args.phase!='camera' or report['full_turn_observed']) else 1


def setup(args):
    import tkinter as tk
    from tkinter import ttk,filedialog
    import os,subprocess,sys
    root=tk.Tk();root.title('W运动 / 镜头标定');root.geometry('760x335')
    config=tk.StringVar(value=str(args.config));mask=tk.StringVar(value=str(args.walk_mask or ''));status=tk.StringVar(value='W可直接测：把角色放在平坦开阔处、前方留出空间，保持镜头固定。可走图可留空。F12停止。')
    def row(label,var):
        frame=ttk.Frame(root);frame.pack(fill='x',padx=12,pady=7)
        ttk.Label(frame,text=label,width=12).pack(side='left');ttk.Entry(frame,textvariable=var).pack(side='left',fill='x',expand=True)
        def choose():
            path=filedialog.askopenfilename(parent=root)
            if path:var.set(path)
        ttk.Button(frame,text='选择',command=choose).pack(side='right')
    row('定位配置JSON',config);row('可走PNG(可选)',mask)
    holds=tk.StringVar(value=' '.join(str(x) for x in args.holds))
    frame=ttk.Frame(root);frame.pack(fill='x',padx=12,pady=5)
    ttk.Label(frame,text='W时长(秒)',width=12).pack(side='left');ttk.Entry(frame,textvariable=holds).pack(side='left',fill='x',expand=True)
    ttk.Label(frame,text='逐级测试，单次≤2秒').pack(side='right')
    children=[]
    def launch(phase,reverse=False):
        if any(p.poll() is None for p in children):status.set('已有标定运行，请先按F12停止。');return
        if not Path(config.get()).is_file():status.set('请先选择当前地图的 patrol-config.json');return
        if mask.get() and not Path(mask.get()).is_file():status.set('可走PNG路径不存在，请重新选择或清空后直接测。');return
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src');env['PYTHONIOENCODING']='utf-8'
        cmd=[sys.executable,'-B','-m','modular_agent.realtime.motion_probe',phase,'--live','--config',config.get()]
        if reverse:cmd+=['--mouse-step','-24']
        if mask.get():cmd+=['--walk-mask',mask.get()]
        elif phase=='forward':cmd+=['--open-ground']
        if phase=='forward':
            try:schedule=[float(x) for x in holds.get().replace(',',' ').split()]
            except ValueError:status.set('W时长请填秒数，例如：0.3 0.6 1.2');return
            if not 2<=len(schedule)<=4 or not all(.05<=x<=2 for x in schedule):status.set('填写2至4组时长，每组0.05至2秒');return
            cmd+=['--holds',*[str(x) for x in sorted(schedule)]]
        output=ROOT/'runtime/patrol/motion-probes'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output.parent.mkdir(parents=True,exist_ok=True);logpath=output.with_suffix('.log');cmd+=['--output',str(output)]
        with logpath.open('w',encoding='utf-8') as stream:
            child=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        children.append(child)
        def poll():
            if child.poll() is None:root.after(1000,poll);return
            try:
                result=read_json(output/'summary.json');report=result.get('report') or {}
                measured=(f"；完整一圈约{report['counts_per_360']:.1f}计数" if report.get('full_turn_observed') else '；未完成一圈，候选估计不可当完整标定') if 'counts_per_360' in report else ''
                if result.get('phase')=='forward':
                    speed=result.get('speed_measurement') or {}
                    measured=(f"；实测稳定速度 {speed['steady_speed_pixels_per_second']:.2f} 地图像素/秒" if speed.get('plateau_observed') else '；尚未观测到稳定速度平台')
                status.set(f"结束：{result['reason']}{measured}；诊断：{output}")
            except (OSError,ValueError,KeyError):status.set(f'启动失败，查看日志：{logpath}')
        root.after(1000,poll)
        status.set('8秒内切回游戏；保持角色原地（镜头）或站在开阔处（W）。结果在 runtime/patrol/motion-probes。')
    ttk.Button(root,text='原地测镜头一圈计数（会移动鼠标）',command=lambda:launch('camera')).pack(fill='x',padx=12,pady=5)
    ttk.Button(root,text='反向镜头复测（会移动鼠标）',command=lambda:launch('camera',True)).pack(fill='x',padx=12,pady=5)
    ttk.Button(root,text='测W稳定速度 / 加速 / 松键滑行（无需先标地图）',command=lambda:launch('forward')).pack(fill='x',padx=12,pady=5)
    ttk.Label(root,textvariable=status,wraplength=725).pack(fill='x',padx=12,pady=8)
    root.mainloop();return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('camera','forward'),nargs='?')
    parser.add_argument('--live',action='store_true');parser.add_argument('--config',type=Path)
    parser.add_argument('--walk-mask',type=Path);parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--open-ground',action='store_true',help='explicit short W test on user-selected open ground; no annotation required')
    parser.add_argument('--window-title',default='hololive-dreams');parser.add_argument('--start-delay',type=float,default=8)
    parser.add_argument('--steps',type=int,default=512);parser.add_argument('--mouse-step',type=int,default=24)
    parser.add_argument('--holds',type=float,nargs='+',default=[.3,.6,1.2])
    parser.add_argument('--coast',type=float,default=1.2)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime/patrol/motion-probes'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    args=parser.parse_args(argv)
    if not 0<=args.start_delay<=30 or not 8<=args.steps<=600 or not 1<=abs(args.mouse_step)<=40 or args.steps*abs(args.mouse_step)>16000 or not 2<=len(args.holds)<=4 or not all(.05<=x<=2 for x in args.holds) or not .2<=args.coast<=2:parser.error('标定预算超限')
    if args.phase and not args.live:parser.error('实机探测必须显式使用 --live')
    if args.phase=='forward' and not (args.walk_mask or args.open_ground):parser.error('W探测请选择 --walk-mask 或 --open-ground 直接测试')
    args.holds=sorted(args.holds)
    args.config=args.config or latest_repaired_config();cv2.setNumThreads(1)
    if not args.phase:return setup(args)
    with route_input_lease(ROOT/'runtime/patrol/route-input.lock'):return run(args)


if __name__=='__main__':raise SystemExit(main())
